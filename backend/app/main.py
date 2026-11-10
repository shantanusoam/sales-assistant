"""FastAPI app: session authentication, browser streaming, Twilio Media Streams, retrieval, and hints."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
import struct
from typing import Awaitable, Callable

from urllib.parse import quote_plus
import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request, WebSocket
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select
from starlette.websockets import WebSocketDisconnect

from .agent import HintAgent
from .auth import extract_ws_token, verify_token
from .auth_routes import build_auth_router
from .calls_routes import build_calls_router
from .crm import CRMError, build_provider
from .crm_routes import build_crm_router
from .playbook_routes import build_playbook_router
from .webhook_routes import build_webhook_router
from .crypto import decrypt_secret
from .config import ROOT, Settings
from .db import create_all, make_db
from .deepgram import DeepgramStream
from .speech_sarvam import SarvamStream
from .deps import build_current_claims_dependency
from .knowledge import KnowledgeBase
from .models import Call, CallSummary, CRMConnection, Hint, Turn, User, WebhookNode
from .post_call import TurnLike, generate_call_summary
from .signals import CUSTOMER_SOURCES, REP_SOURCES, CallSignals, tag_turn

logger = logging.getLogger(__name__)
FRONTEND = ROOT / "frontend"


class OutboundCallRequest(BaseModel):
    to: str = Field(min_length=3, max_length=32, description="Destination phone number in E.164 format")
    dial: str | None = Field(default=None, max_length=32, description="Optional second number to bridge")
    consent_confirmed: bool = Field(default=False, description="Rep has informed the other party and has their consent")


class MobileTurnInput(BaseModel):
    speaker: str = Field(default="customer", description="'customer' or 'rep'")
    text: str = Field(min_length=1, max_length=1200)


class MobileCallLogRequest(BaseModel):
    to_number: str | None = Field(default=None, max_length=32, description="Prospect phone number or identifier")
    consent_confirmed: bool = Field(default=False, description="Whether participant consent was confirmed")
    turns: list[MobileTurnInput] = Field(min_length=1, max_length=100)


def _pcm16_16k_to_ulaw_8k(pcm16_16k: bytes) -> bytes:
    """Downsample 16 kHz 16-bit signed linear PCM to 8 kHz G.711 mu-law for Twilio playback."""
    count = len(pcm16_16k) // 2
    if count == 0:
        return b""
    samples = struct.unpack(f"<{count}h", pcm16_16k[: count * 2])
    out = bytearray()
    BIAS = 0x84
    CLIP = 32635
    for s in samples[::2]:
        sign = 0x80 if s < 0 else 0
        if s < 0:
            s = -s
        if s > CLIP:
            s = CLIP
        s += BIAS
        exp = 7
        mask = 0x4000
        while exp > 0 and not (s & mask):
            exp -= 1
            mask >>= 1
        mant = (s >> (exp + 3)) & 0x0F
        out.append(~(sign | (exp << 4) | mant) & 0xFF)
    return bytes(out)


ULAW_TO_PCM16: list[int] = []
for _b in range(256):
    _u = ~_b & 0xFF
    _sign = _u & 0x80
    _exp = (_u >> 4) & 0x07
    _mant = _u & 0x0F
    _sample = ((_mant << 3) + 0x84) << _exp
    _sample -= 0x84
    ULAW_TO_PCM16.append(-_sample if _sign else _sample)


def _ulaw_8k_to_pcm16_16k_b64(ulaw_8k: bytes) -> tuple[str, float]:
    """Decode 8 kHz G.711 mu-law to 16 kHz PCM16-LE (base64) + RMS level for browser speaker playback."""
    if not ulaw_8k:
        return "", 0.0
    samples_16k: list[int] = []
    sq_sum = 0.0
    for b in ulaw_8k:
        s = ULAW_TO_PCM16[b]
        samples_16k.append(s)
        samples_16k.append(s)
        sq_sum += s * s
    rms = (sq_sum / len(ulaw_8k)) ** 0.5 / 32768.0
    pcm_bytes = struct.pack(f"<{len(samples_16k)}h", *samples_16k)
    return base64.b64encode(pcm_bytes).decode("ascii"), round(rms, 4)


def _mic_stt_configured(config: Settings) -> bool:
    """Whether live browser-mic transcription has a usable provider key, for whichever STT_PROVIDER is selected."""
    return bool(config.sarvam_api_key) if config.stt_provider == "sarvam" else bool(config.deepgram_api_key)


def _open_mic_stt_stream(config: Settings) -> DeepgramStream | SarvamStream:
    """16 kHz PCM16 mic stream — matches Sarvam's native format directly, no resampling needed."""
    if config.stt_provider == "sarvam":
        return SarvamStream(config, sample_rate=16000)
    return DeepgramStream(config)


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings()
    engine, get_db, db_sessions = make_db(config)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if config.database_url.startswith("sqlite"):
            await create_all(engine)
        yield
        await engine.dispose()

    application = FastAPI(title="Sales Copilot MVP", docs_url=None, redoc_url=None, lifespan=lifespan)
    application.mount("/assets", StaticFiles(directory=str(FRONTEND)), name="assets")
    knowledge = KnowledgeBase(config)
    agent = HintAgent(config)
    live_broadcasters: dict[str, set[Callable[[dict], Awaitable[None]]]] = defaultdict(set)
    twilio_outbound_senders: dict[str, set[Callable[[bytes], Awaitable[None]]]] = defaultdict(set)
    require_auth = build_current_claims_dependency(config)
    application.include_router(build_auth_router(config, get_db))
    application.include_router(build_calls_router(get_db, require_auth, config))
    application.include_router(build_crm_router(config, get_db, require_auth))
    application.include_router(build_webhook_router(get_db, require_auth))
    application.include_router(build_playbook_router(config, knowledge, require_auth))

    async def summarize_call(call_id: str) -> None:
        """Runs after a call ends: generates and persists its post-call summary.

        Awaited (not fire-and-forget) from within the same asyncio.shield() that
        protects the call's own ended_at write — a detached asyncio.create_task()
        here is not reliably driven to completion by every ASGI server/test harness
        once the websocket's own task is finishing up, so this keeps it on the same
        awaited, cancellation-shielded chain that already works for that write.
        """
        try:
            async with db_sessions() as db:
                call = await db.get(Call, call_id)
                rows = await db.scalars(select(Turn).where(Turn.call_id == call_id).order_by(Turn.seq))
                turns = [TurnLike(t.source, t.text) for t in rows]
            data = await generate_call_summary(turns, config)
            # Nothing gets pushed to a third party unless the rep confirmed consent for
            # this call — see /ws/live's "confirm_consent" message and the Twilio
            # customParameters path. Internal Call History still shows the summary either way.
            if call and call.organization_id and call.consent_confirmed_at:
                await push_summary_to_crm(call.organization_id, data, call.started_at)
                await push_summary_to_whatsapp(call, data)
                await push_summary_to_webhooks(call.organization_id, call_id, data)
            async with db_sessions() as db:
                db.add(CallSummary(
                    call_id=call_id, summary=data["summary"], coaching_score=data["coaching_score"],
                    coaching_notes=data["coaching_notes"], follow_up_email=data["follow_up_email"],
                    disposition=data["disposition"], method=data["method"],
                ))
                await db.commit()
        except Exception:
            logger.exception("Post-call summary generation failed for call %s", call_id)

    async def push_summary_to_crm(organization_id: str, summary_data: dict, call_time) -> None:
        async with db_sessions() as db:
            conn = await db.scalar(select(CRMConnection).where(CRMConnection.organization_id == organization_id))
            if not conn or not conn.auto_push:
                return
            try:
                token = decrypt_secret(conn.encrypted_token, config)
                provider = build_provider(conn.provider, token)
                note = (
                    f"Sales Copilot call summary (coaching score {summary_data['coaching_score']}/100, "
                    f"disposition: {summary_data['disposition'].replace('_', ' ')})\n\n"
                    f"{summary_data['summary']}\n\n"
                    f"Coaching notes: {summary_data['coaching_notes']}\n\n"
                    f"Suggested follow-up email:\n{summary_data['follow_up_email']}"
                )
                await provider.push_call_note(note, call_time)
            except CRMError:
                logger.exception("CRM push failed for org %s", organization_id)
            except Exception:
                logger.exception("Unexpected error pushing call summary to CRM for org %s", organization_id)

    async def push_summary_to_whatsapp(call: Call, summary_data: dict) -> None:
        if not call.rep_user_id:
            return
        async with db_sessions() as db:
            user = await db.get(User, call.rep_user_id)
        if not user or not user.whatsapp_recap_enabled or not user.whatsapp_number:
            return
        if not (config.twilio_account_sid and config.twilio_auth_token
                and config.twilio_whatsapp_from and config.twilio_whatsapp_template_sid):
            logger.info("WhatsApp recap skipped for user %s: Twilio WhatsApp sender/template not configured", user.id)
            return
        try:
            twilio_api = f"https://api.twilio.com/2010-04-01/Accounts/{config.twilio_account_sid}/Messages.json"
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    twilio_api,
                    auth=(config.twilio_account_sid, config.twilio_auth_token),
                    data={
                        "To": f"whatsapp:{user.whatsapp_number}",
                        "From": f"whatsapp:{config.twilio_whatsapp_from}",
                        "ContentSid": config.twilio_whatsapp_template_sid,
                        "ContentVariables": json.dumps({
                            "1": summary_data["disposition"].replace("_", " ").title(),
                            "2": str(summary_data["coaching_score"]),
                            "3": summary_data["summary"][:300],
                        }),
                    },
                )
            if resp.status_code >= 400:
                logger.warning("WhatsApp recap failed for user %s (%s): %s", user.id, resp.status_code, resp.text[:200])
        except Exception:
            logger.exception("WhatsApp recap delivery failed for user %s", user.id)

    async def push_summary_to_webhooks(organization_id: str, call_id: str, summary_data: dict) -> None:
        async with db_sessions() as db:
            nodes = list(await db.scalars(
                select(WebhookNode).where(WebhookNode.organization_id == organization_id, WebhookNode.enabled == True)  # noqa: E712
            ))
        if not nodes:
            return
        payload = {
            "event": "call.summary_ready",
            "call_id": call_id,
            "disposition": summary_data["disposition"],
            "coaching_score": summary_data["coaching_score"],
            "summary": summary_data["summary"],
            "coaching_notes": summary_data["coaching_notes"],
            "follow_up_email": summary_data["follow_up_email"],
            "method": summary_data["method"],
        }
        body = json.dumps(payload, sort_keys=True).encode()
        for node in nodes:
            signature = hmac.new(node.secret.encode(), body, hashlib.sha256).hexdigest()
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(
                        node.url, content=body,
                        headers={"Content-Type": "application/json", "X-Signature-SHA256": signature},
                    )
                if resp.status_code >= 400:
                    logger.warning("Webhook node %s returned %s", node.id, resp.status_code)
            except Exception:
                logger.exception("Webhook delivery failed for node %s", node.id)

    async def broadcast_to_dashboards(payload: dict, org_id: str | None = None) -> None:
        if org_id:
            targets = list(live_broadcasters.get(org_id, ()))
            for sender in targets:
                try:
                    await sender(payload)
                except Exception:
                    live_broadcasters[org_id].discard(sender)
            return
        for bucket in list(live_broadcasters.values()):
            for sender in list(bucket):
                try:
                    await sender(payload)
                except Exception:
                    bucket.discard(sender)

    async def forward_mic_to_twilio(org_id: str, ulaw_8k: bytes) -> None:
        for sender in list(twilio_outbound_senders.get(org_id, ())):
            try:
                await sender(ulaw_8k)
            except Exception:
                twilio_outbound_senders[org_id].discard(sender)

    FAVICON_SVG = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 34 34">'
        '<rect width="34" height="34" rx="10" fill="#2e84ba"/>'
        '<rect x="8" y="17" width="4" height="9" rx="2" fill="#fff"/>'
        '<rect x="15" y="10" width="4" height="16" rx="2" fill="#fff"/>'
        '<rect x="22" y="14" width="4" height="12" rx="2" fill="#fff"/>'
        '</svg>'
    )

    @application.get("/favicon.ico", include_in_schema=False)
    @application.get("/favicon.svg", include_in_schema=False)
    async def favicon() -> Response:
        return Response(content=FAVICON_SVG, media_type="image/svg+xml")

    @application.get("/manifest.webmanifest", include_in_schema=False)
    async def pwa_manifest() -> FileResponse:
        return FileResponse(FRONTEND / "manifest.webmanifest", media_type="application/manifest+json")

    @application.get("/sw.js", include_in_schema=False)
    async def service_worker() -> FileResponse:
        return FileResponse(FRONTEND / "sw.js", media_type="application/javascript")

    @application.get("/")
    async def index() -> FileResponse:
        return FileResponse(FRONTEND / "index.html")

    @application.get("/login")
    async def login_page() -> FileResponse:
        return FileResponse(FRONTEND / "login.html")

    @application.get("/signup")
    async def signup_page() -> FileResponse:
        return FileResponse(FRONTEND / "signup.html")

    @application.get("/history")
    async def history_page() -> FileResponse:
        return FileResponse(FRONTEND / "history.html")

    @application.get("/settings")
    async def settings_page() -> FileResponse:
        return FileResponse(FRONTEND / "settings.html")

    @application.get("/api/health")
    async def health() -> dict:
        db_ok = True
        try:
            async for session in get_db():
                await session.execute(select(1))
        except Exception:
            db_ok = False
        return {
            "ok": True,
            "auth_configured": config.configured,
            "database_ok": db_ok,
            "microphone_transcription_configured": _mic_stt_configured(config),
            "stt_provider": config.stt_provider,
            "llm_configured": bool(config.openai_api_key),
            "twilio_configured": bool(config.twilio_account_sid and config.twilio_auth_token and config.twilio_phone_number),
            "twilio_default_to": config.twilio_default_to,
            "retrieval_mode": knowledge.mode,
            "document_chunks": len(knowledge.chunks),
        }

    @application.post("/api/calls/log-mobile")
    async def log_mobile_call(payload: MobileCallLogRequest, claims: dict = Depends(require_auth)) -> dict:
        """Truecaller-style post-call / field-sales mobile call logger: records turns,
        generates a grounded playbook hint + post-call summary, and distributes to
        CRM/WhatsApp/webhooks when consent_confirmed is True."""
        now = datetime.now(timezone.utc)
        clean_turns: list[tuple[str, str, str, list[str]]] = []
        for item in payload.turns:
            text = " ".join(item.text.strip().split())[:1200]
            if not text:
                continue
            source = "twilio-customer" if item.speaker == "customer" else "twilio-rep"
            sentiment, intents = tag_turn(text)
            clean_turns.append((source, text, sentiment, intents))
        if not clean_turns:
            raise HTTPException(400, "At least one non-empty conversation turn is required.")

        last_utterance = clean_turns[-1][1]
        recent_texts = [t[1] for t in clean_turns[:-1]]
        started = time.perf_counter()
        sources = await knowledge.retrieve(last_utterance)
        hint_text, hint_method = await agent.generate(last_utterance, recent_texts, sources)
        public_sources = [s.public() for s in sources]
        processing_ms = int((time.perf_counter() - started) * 1000)

        async with db_sessions() as db:
            call = Call(
                organization_id=claims["org_id"],
                rep_user_id=claims["user_id"],
                channel="mobile",
                to_number=(payload.to_number or "").strip() or None,
                started_at=now,
                ended_at=now,
                consent_confirmed_at=now if payload.consent_confirmed else None,
            )
            db.add(call)
            await db.flush()
            call_id = call.id
            for seq, (source, text, sentiment, intents) in enumerate(clean_turns):
                db.add(Turn(
                    call_id=call_id,
                    seq=seq,
                    source=source,
                    text=text,
                    sentiment=sentiment,
                    intents_json=json.dumps(intents),
                ))
            db.add(Hint(
                call_id=call_id,
                text=hint_text,
                method=hint_method,
                sources_json=json.dumps(public_sources),
                processing_ms=processing_ms,
            ))
            await db.commit()

        await summarize_call(call_id)
        async with db_sessions() as db:
            summary_row = await db.scalar(select(CallSummary).where(CallSummary.call_id == call_id))
        return {
            "id": call_id,
            "channel": "mobile",
            "to_number": (payload.to_number or "").strip() or None,
            "consent_confirmed": payload.consent_confirmed,
            "turn_count": len(clean_turns),
            "hint": {
                "text": hint_text,
                "method": hint_method,
                "sources": public_sources,
                "processing_ms": processing_ms,
            },
            "summary": {
                "text": summary_row.summary,
                "coaching_score": summary_row.coaching_score,
                "coaching_notes": summary_row.coaching_notes,
                "follow_up_email": summary_row.follow_up_email,
                "disposition": summary_row.disposition,
                "method": summary_row.method,
            } if summary_row else None,
        }

    @application.post("/api/twilio/call")
    async def start_outbound_call(request: Request, payload: OutboundCallRequest, claims: dict = Depends(require_auth)) -> dict:
        if not (config.twilio_account_sid and config.twilio_auth_token and config.twilio_phone_number):
            raise HTTPException(400, "Twilio credentials are not configured in .env.")
        raw_to = "".join(c for c in payload.to.strip() if c.isdigit() or c == "+")
        if not raw_to:
            raise HTTPException(400, "Enter a valid phone number.")
        if not raw_to.startswith("+"):
            raw_to = f"+91{raw_to}" if len(raw_to) == 10 else f"+{raw_to}"

        base_url = ""
        tunnel_file = ROOT / ".tunnel_url"
        if tunnel_file.exists():
            base_url = tunnel_file.read_text(encoding="utf-8").strip().rstrip("/")
        if not base_url:
            base_url = (config.public_base_url or "").rstrip("/")
        if not base_url:
            host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
            scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
            if host and not host.startswith(("localhost", "127.0.0.1")):
                base_url = f"{scheme}://{host}"
        if not base_url:
            raise HTTPException(400, "PUBLIC_BASE_URL is required in .env so Twilio can reach your local server.")

        twiml_params = {
            "org_id": claims["org_id"],
            "rep_user_id": claims["user_id"],
            "to_number": raw_to,
            "from_number": config.twilio_phone_number,
        }
        if payload.consent_confirmed:
            twiml_params["consent"] = "1"
        if payload.dial and payload.dial.strip():
            raw_dial = "".join(c for c in payload.dial.strip() if c.isdigit() or c == "+")
            if raw_dial and not raw_dial.startswith("+"):
                raw_dial = f"+91{raw_dial}" if len(raw_dial) == 10 else f"+{raw_dial}"
            if raw_dial:
                twiml_params["dial"] = raw_dial
        twiml_url = f"{base_url}/api/twilio/twiml?" + "&".join(f"{k}={quote_plus(v)}" for k, v in twiml_params.items())

        twilio_api = f"https://api.twilio.com/2010-04-01/Accounts/{config.twilio_account_sid}/Calls.json"
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                twilio_api,
                auth=(config.twilio_account_sid, config.twilio_auth_token),
                data={
                    "To": raw_to,
                    "From": config.twilio_phone_number,
                    "Url": twiml_url,
                },
            )
        data = resp.json()
        if resp.status_code >= 400:
            msg = data.get("message") or "Twilio rejected the call request."
            raise HTTPException(resp.status_code, msg)
        return {
            "ok": True,
            "call_sid": data.get("sid"),
            "status": data.get("status"),
            "to": raw_to,
            "from": config.twilio_phone_number,
        }

    @application.api_route("/api/twilio/twiml", methods=["GET", "POST"])
    async def twilio_twiml(
        request: Request,
        dial: str | None = Query(default=None, description="Optional second number (+91...) to bridge"),
        org_id: str | None = Query(default=None, description="Organization that owns this call, for persistence"),
        rep_user_id: str | None = Query(default=None, description="Rep who placed this call, for persistence"),
        consent: str | None = Query(default=None, description="'1' if the rep confirmed consent before dialing"),
        to_number: str | None = Query(default=None, description="Destination phone number"),
        from_number: str | None = Query(default=None, description="Caller phone number"),
    ) -> Response:
        """
        TwiML webhook for Twilio Voice calls. Starts a Twilio Media Stream (<Start><Stream>)
        that pipes live 8kHz mu-law call audio to /ws/twilio-media, so Deepgram transcribes
        the call and pushes real-time sales hints to the connected Copilot dashboard.
        """
        host = request.headers.get("x-forwarded-host") or request.headers.get("host") or "localhost:8765"
        ws_scheme = "ws" if host.startswith(("localhost", "127.0.0.1")) else "wss"
        ws_url = f"{ws_scheme}://{host}/ws/twilio-media"
        stream_params = "".join(
            f'<Parameter name="{name}" value="{value}" />'
            for name, value in (
                ("org_id", org_id),
                ("rep_user_id", rep_user_id),
                ("consent", consent),
                ("to_number", to_number),
                ("from_number", from_number),
            )
            if value
        )

        if dial:
            xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Start>
        <Stream name="sales-copilot" url="{ws_url}" track="both_tracks">{stream_params}</Stream>
    </Start>
    <Say>Sales Copilot is active. Connecting your call now.</Say>
    <Dial>
        <Number>{dial}</Number>
    </Dial>
</Response>"""
        else:
            xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say>Sales Copilot is connected. Speak your sales question or objection now, and watch your browser dashboard. Everything you say on the phone or in your browser microphone will also play back to your phone.</Say>
    <Connect>
        <Stream name="sales-copilot" url="{ws_url}">{stream_params}</Stream>
    </Connect>
</Response>"""
        return Response(content=xml, media_type="application/xml")

    @application.websocket("/ws/twilio-media")
    async def twilio_media(ws: WebSocket) -> None:
        """
        Ingests Twilio Media Streams 8kHz mu-law audio frames, forwards them to Deepgram
        (encoding=mulaw, sample_rate=8000), and broadcasts live transcripts and Copilot
        playbook hints to all connected browser dashboards.
        """
        await ws.accept()
        queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue(maxsize=1)
        history: deque[str] = deque(maxlen=7)
        last_queued: str = ""
        streams: dict[str, DeepgramStream] = {}
        tasks: list[asyncio.Task] = []
        call_sid: str = "twilio-call"
        stream_sid: str = ""
        call_org_id: str | None = None
        ws_send_lock = asyncio.Lock()
        db_call_id: str | None = None
        turn_seq = 0
        signals = CallSignals()

        async def open_db_call(
            org_id: str | None,
            rep_user_id: str | None,
            twilio_call_sid: str,
            consent: str | None,
            to_number: str | None = None,
            from_number: str | None = None,
        ) -> None:
            nonlocal db_call_id, call_org_id
            call_org_id = org_id
            if not org_id:
                return
            async with db_sessions() as db:
                call = Call(
                    organization_id=org_id,
                    rep_user_id=rep_user_id,
                    channel="twilio",
                    twilio_call_sid=twilio_call_sid,
                    to_number=to_number,
                    from_number=from_number,
                    consent_confirmed_at=datetime.now(timezone.utc) if consent == "1" else None,
                )
                db.add(call)
                await db.commit()
                db_call_id = call.id

        async def record_db_turn(text: str, source: str, sentiment: str, intents: list[str]) -> None:
            nonlocal turn_seq
            if not db_call_id:
                return
            seq, turn_seq = turn_seq, turn_seq + 1

            async def _write() -> None:
                async with db_sessions() as db:
                    db.add(Turn(call_id=db_call_id, seq=seq, source=source, text=text,
                                 sentiment=sentiment, intents_json=json.dumps(intents)))
                    await db.commit()

            await asyncio.shield(_write())

        async def record_db_hint(text: str, method: str, sources: list, processing_ms: int) -> None:
            if not db_call_id:
                return

            async def _write() -> None:
                async with db_sessions() as db:
                    db.add(Hint(call_id=db_call_id, text=text, method=method,
                                 sources_json=json.dumps(sources), processing_ms=processing_ms))
                    await db.commit()

            await asyncio.shield(_write())

        async def close_db_call() -> None:
            if not db_call_id:
                return

            async def _write() -> None:
                async with db_sessions() as db:
                    call = await db.get(Call, db_call_id)
                    if call:
                        call.ended_at = datetime.now(timezone.utc)
                        await db.commit()
                if turn_seq > 0:
                    await summarize_call(db_call_id)

            await asyncio.shield(_write())

        async def send_ulaw_to_phone(ulaw_bytes: bytes) -> None:
            if not stream_sid or not ulaw_bytes:
                return
            payload_b64 = base64.b64encode(ulaw_bytes).decode("ascii")
            async with ws_send_lock:
                await ws.send_json({
                    "event": "media",
                    "streamSid": stream_sid,
                    "media": {"payload": payload_b64},
                })

        async def enqueue_utterance(text: str, track_source: str) -> None:
            nonlocal last_queued
            normalized = " ".join(text.strip().split())[:1200]
            if not normalized:
                return
            sentiment, intents = tag_turn(normalized)
            await broadcast_to_dashboards({
                "type": "transcript_final",
                "text": normalized,
                "source": track_source,
                "sentiment": sentiment,
                "intents": intents,
            }, org_id=call_org_id)
            await record_db_turn(normalized, track_source, sentiment, intents)
            signals.record(normalized, track_source, sentiment, intents)
            await broadcast_to_dashboards(signals.public(REP_SOURCES, CUSTOMER_SOURCES), org_id=call_org_id)
            history.append(normalized)
            if len(normalized) < 5 or normalized.casefold() == last_queued:
                return
            last_queued = normalized.casefold()
            if queue.full():
                try:
                    queue.get_nowait()
                    queue.task_done()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait((normalized, track_source))

        async def twilio_hint_worker() -> None:
            last_start = 0.0
            while True:
                utterance, _source = await queue.get()
                try:
                    delta = time.monotonic() - last_start
                    if delta < config.hint_cooldown_seconds:
                        await asyncio.sleep(config.hint_cooldown_seconds - delta)
                    last_start = time.monotonic()
                    started = time.perf_counter()
                    sources = await knowledge.retrieve(utterance)
                    hint, method = await agent.generate(utterance, list(history), sources)
                    public_sources = [s.public() for s in sources]
                    processing_ms = int((time.perf_counter() - started) * 1000)
                    await broadcast_to_dashboards({
                        "type": "hint",
                        "text": hint,
                        "method": method,
                        "sources": public_sources,
                        "retrieval_mode": knowledge.mode,
                        "processing_ms": processing_ms,
                    }, org_id=call_org_id)
                    await record_db_hint(hint, method, public_sources, processing_ms)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Twilio hint generation failed")
                finally:
                    queue.task_done()

        async def get_or_open_stt(track: str) -> DeepgramStream | SarvamStream | None:
            if track in streams:
                return streams[track]
            if config.stt_provider == "sarvam":
                if not config.sarvam_api_key:
                    return None
                dg = SarvamStream(config, sample_rate=16000)
            else:
                if not config.deepgram_api_key:
                    return None
                dg = DeepgramStream(config, encoding="mulaw", sample_rate=8000)
            await dg.open()
            streams[track] = dg
            source_label = "twilio-customer" if track == "inbound" else "twilio-rep"

            async def on_interim(text: str) -> None:
                await broadcast_to_dashboards({"type": "transcript_interim", "text": f"[{track}] {text}"}, org_id=call_org_id)

            async def on_final(text: str) -> None:
                await enqueue_utterance(text, source_label)

            async def on_err(msg: str) -> None:
                logger.warning("Twilio STT error (%s, %s): %s", config.stt_provider, track, msg)

            async def keepalive() -> None:
                while True:
                    await asyncio.sleep(5)
                    await dg.keepalive()

            tasks.append(asyncio.create_task(dg.consume(on_interim, on_final, on_err)))
            tasks.append(asyncio.create_task(keepalive()))
            return dg

        worker = asyncio.create_task(twilio_hint_worker())
        tasks.append(worker)
        try:
            while True:
                raw = await ws.receive_text()
                event = json.loads(raw)
                kind = event.get("event")
                if kind == "start":
                    start_info = event.get("start", {})
                    call_sid = start_info.get("callSid", "twilio-call")
                    stream_sid = start_info.get("streamSid", "")
                    custom_params = start_info.get("customParameters", {}) or {}
                    await open_db_call(
                        custom_params.get("org_id"),
                        custom_params.get("rep_user_id"),
                        call_sid,
                        custom_params.get("consent"),
                        custom_params.get("to_number"),
                        custom_params.get("from_number"),
                    )
                    if call_org_id:
                        twilio_outbound_senders[call_org_id].add(send_ulaw_to_phone)
                    await broadcast_to_dashboards({
                        "type": "status",
                        "message": f"Twilio phone call connected ({call_sid}) — two-way audio + live {config.stt_provider.title()} transcription active!",
                    }, org_id=call_org_id)
                elif kind == "media":
                    media = event.get("media", {})
                    track = media.get("track", "inbound")
                    payload_b64 = media.get("payload", "")
                    if payload_b64:
                        audio_bytes = base64.b64decode(payload_b64)
                        pcm_b64, rms = _ulaw_8k_to_pcm16_16k_b64(audio_bytes)
                        if pcm_b64:
                            await broadcast_to_dashboards({
                                "type": "phone_audio",
                                "pcm16_b64": pcm_b64,
                                "rms": rms,
                            }, org_id=call_org_id)
                        dg = await get_or_open_stt(track)
                        if dg:
                            if config.stt_provider == "sarvam":
                                if pcm_b64:
                                    await dg.send_audio(base64.b64decode(pcm_b64))
                            else:
                                await dg.send_audio(audio_bytes)
                elif kind == "stop":
                    await broadcast_to_dashboards({
                        "type": "status",
                        "message": f"Twilio phone call ended ({call_sid}).",
                    }, org_id=call_org_id)
                    break
        except WebSocketDisconnect:
            pass
        except Exception:
            logger.exception("Twilio media stream error")
        finally:
            if call_org_id:
                twilio_outbound_senders[call_org_id].discard(send_ulaw_to_phone)
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            for dg in streams.values():
                await dg.close()
            await close_db_call()

    @application.websocket("/ws/live")
    async def live(ws: WebSocket) -> None:
        origin = ws.headers.get("origin")
        if origin not in config.allowed_origins:
            await ws.close(code=1008, reason="Origin not allowed")
            return
        token = extract_ws_token(ws.headers.get("sec-websocket-protocol", ""))
        claims = verify_token(token, config)
        if not claims:
            await ws.close(code=1008, reason="Invalid or expired session token")
            return
        await ws.accept(subprotocol="copilot-v1")
        send_lock = asyncio.Lock()
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=1)
        history: deque[str] = deque(maxlen=7)
        deepgram: DeepgramStream | SarvamStream | None = None
        deepgram_listener: asyncio.Task | None = None
        deepgram_keepalive: asyncio.Task | None = None
        last_queued: str = ""
        call_id: str | None = None
        turn_seq = 0
        signals = CallSignals()

        async def open_call() -> None:
            nonlocal call_id
            async with db_sessions() as db:
                call = Call(organization_id=claims["org_id"], rep_user_id=claims["user_id"], channel="browser")
                db.add(call)
                await db.commit()
                call_id = call.id

        async def confirm_consent() -> None:
            if not call_id:
                return
            async with db_sessions() as db:
                call = await db.get(Call, call_id)
                if call and not call.consent_confirmed_at:
                    call.consent_confirmed_at = datetime.now(timezone.utc)
                    await db.commit()

        async def record_turn(text: str, source: str, sentiment: str, intents: list[str]) -> None:
            nonlocal turn_seq
            if not call_id:
                return
            seq, turn_seq = turn_seq, turn_seq + 1

            async def _write() -> None:
                async with db_sessions() as db:
                    db.add(Turn(call_id=call_id, seq=seq, source=source, text=text,
                                 sentiment=sentiment, intents_json=json.dumps(intents)))
                    await db.commit()

            await asyncio.shield(_write())

        async def record_hint(text: str, method: str, sources: list, processing_ms: int) -> None:
            if not call_id:
                return

            async def _write() -> None:
                async with db_sessions() as db:
                    db.add(Hint(call_id=call_id, text=text, method=method,
                                 sources_json=json.dumps(sources), processing_ms=processing_ms))
                    await db.commit()

            await asyncio.shield(_write())

        async def close_call() -> None:
            if not call_id:
                return

            async def _write() -> None:
                async with db_sessions() as db:
                    call = await db.get(Call, call_id)
                    if call:
                        call.ended_at = datetime.now(timezone.utc)
                        await db.commit()
                if turn_seq > 0:
                    await summarize_call(call_id)

            await asyncio.shield(_write())

        async def send(payload: dict) -> None:
            async with send_lock:
                await ws.send_json(payload)

        live_broadcasters[claims["org_id"]].add(send)
        await open_call()

        async def enqueue(text: str, source: str) -> None:
            nonlocal last_queued
            normalized = " ".join(text.strip().split())[:1200]
            if not normalized:
                return
            sentiment, intents = tag_turn(normalized)
            await send({"type": "transcript_final", "text": normalized, "source": source,
                        "sentiment": sentiment, "intents": intents})
            await record_turn(normalized, source, sentiment, intents)
            signals.record(normalized, source, sentiment, intents)
            await send(signals.public(REP_SOURCES, CUSTOMER_SOURCES))
            history.append(normalized)
            if len(normalized) < 5 or normalized.casefold() == last_queued:
                return
            last_queued = normalized.casefold()
            if queue.full():
                try:
                    queue.get_nowait()  # latest utterance replaces stale queued work
                    queue.task_done()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(normalized)

        async def hint_worker() -> None:
            last_start = 0.0
            while True:
                utterance = await queue.get()
                try:
                    delta = time.monotonic() - last_start
                    if delta < config.hint_cooldown_seconds:
                        await asyncio.sleep(config.hint_cooldown_seconds - delta)
                    last_start = time.monotonic()
                    started = time.perf_counter()
                    sources = await knowledge.retrieve(utterance)
                    hint, method = await agent.generate(utterance, list(history), sources)
                    public_sources = [s.public() for s in sources]
                    processing_ms = int((time.perf_counter() - started) * 1000)
                    await send({
                        "type": "hint",
                        "text": hint,
                        "method": method,
                        "sources": public_sources,
                        "retrieval_mode": knowledge.mode,
                        "processing_ms": processing_ms,
                    })
                    await record_hint(hint, method, public_sources, processing_ms)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.exception("Hint processing failed")
                    await send({"type": "error", "message": "Hint generation failed. Verify the AI provider key and availability."})
                finally:
                    queue.task_done()

        async def on_interim(text: str) -> None:
            await send({"type": "transcript_interim", "text": text})

        async def on_final(text: str) -> None:
            await enqueue(text, "microphone")

        async def on_deepgram_error(message: str) -> None:
            logger.warning("Deepgram error: %s", message)
            await send({"type": "error", "message": "Streaming transcription failed; check backend logs."})

        async def keepalive_loop(stream: DeepgramStream) -> None:
            while True:
                await asyncio.sleep(5)
                await stream.keepalive()

        async def consume_stream(stream: DeepgramStream) -> None:
            try:
                await stream.consume(on_interim, on_final, on_deepgram_error)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Deepgram stream lost")
                await send({"type": "error", "message": "Transcription connection ended. Reconnect the session."})

        worker = asyncio.create_task(hint_worker(), name="hint-worker")
        try:
            await send({
                "type": "ready",
                "microphone_enabled": _mic_stt_configured(config),
                "stt_provider": config.stt_provider,
                "retrieval_mode": knowledge.mode,
                "llm_enabled": bool(config.openai_api_key),
            })
            while True:
                message = await ws.receive()
                if message.get("type") == "websocket.disconnect":
                    break
                audio = message.get("bytes")
                if audio is not None:
                    if not _mic_stt_configured(config):
                        key_name = "SARVAM_API_KEY" if config.stt_provider == "sarvam" else "DEEPGRAM_API_KEY"
                        await send({"type": "error", "message": f"Add {key_name} to enable microphone transcription."})
                        continue
                    if not audio or len(audio) % 2 or len(audio) > config.max_audio_bytes_per_frame:
                        await send({"type": "error", "message": "Invalid PCM16 audio frame."})
                        continue
                    if deepgram is None:
                        try:
                            deepgram = _open_mic_stt_stream(config)
                            await deepgram.open()
                            deepgram_listener = asyncio.create_task(consume_stream(deepgram))
                            deepgram_keepalive = asyncio.create_task(keepalive_loop(deepgram))
                            await send({"type": "status", "message": "Live transcription connected."})
                        except Exception:
                            logger.exception("Failed to connect %s", config.stt_provider)
                            deepgram = None
                            await send({"type": "error", "message": f"Could not connect to {config.stt_provider.title()}. Check API key/network."})
                            continue
                    try:
                        await deepgram.send_audio(audio)
                        if twilio_outbound_senders.get(claims["org_id"]):
                            await forward_mic_to_twilio(claims["org_id"], _pcm16_16k_to_ulaw_8k(audio))
                    except Exception:
                        logger.exception("Sending audio failed")
                        await send({"type": "error", "message": "Audio stream failed. Reconnect the session."})
                        break
                    continue
                text = message.get("text")
                if text is None:
                    continue
                try:
                    payload = json.loads(text)
                except (ValueError, TypeError):
                    await send({"type": "error", "message": "Invalid JSON control message."})
                    continue
                kind = payload.get("type")
                if kind == "simulate_utterance":
                    utterance = payload.get("text")
                    if not isinstance(utterance, str) or len(utterance) > 700:
                        await send({"type": "error", "message": "Test text must be 700 characters or fewer."})
                    else:
                        speaker = payload.get("speaker")
                        source = "customer-test" if speaker == "customer" else "manual-test"
                        await enqueue(utterance, source)
                elif kind == "end_audio":
                    if deepgram:
                        await deepgram.finalize()
                elif kind == "confirm_consent":
                    await confirm_consent()
                    await send({"type": "status", "message": "Consent recorded for this call."})
                else:
                    await send({"type": "error", "message": "Unknown message type."})
        except WebSocketDisconnect:
            pass
        except Exception:
            logger.exception("Live connection error")
        finally:
            live_broadcasters[claims["org_id"]].discard(send)
            for task in (worker, deepgram_listener, deepgram_keepalive):
                if task:
                    task.cancel()
            await asyncio.gather(*(t for t in (worker, deepgram_listener, deepgram_keepalive) if t), return_exceptions=True)
            if deepgram:
                await deepgram.close()
            await close_call()

    return application


app = create_app()

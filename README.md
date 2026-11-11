# Real-Time Sales Copilot MVP

A runnable **FastAPI + vanilla JavaScript** prototype. It accepts microphone PCM16 frames over an authenticated WebSocket, streams to **Deepgram** for interim/final transcription, retrieves sales playbook excerpts from **ChromaDB using OpenAI embeddings**, creates one concise hint with **OpenAI**, and pushes it to the dashboard without a refresh.

**Works without paid API keys in TEXT TEST MODE:** submit a sample utterance, retrieve local playbook text with a simple lexical search, and see a **rules-based demo hint**. This path is deliberately labeled as a demonstration; it is **not** AI transcription or vector RAG.

## Important scope boundary

**A browser microphone does not capture the other participant in a regular iOS/Android carrier phone call.** This version hears only what your browser microphone captures (typically the rep's voice). It is suitable for testing the backend, UI, suggestion workflow, and permitted in-person or own-side audio. For a real two-sided phone call, integrate a consented telephony media stream (Twilio or similar), or build a genuine web-based calling system (WebRTC), and then ingest both audio channels. Browser microphone permission does not bypass iOS/Android isolation.

Sub-second *interim transcription* may be achievable under good network conditions, but **sub-second finished AI hints are not guaranteed**: speech-end detection, embedding, retrieval, and LLM generation all add latency. The UI reports **backend hint processing time only** (retrieval + generation), not end-to-end speech-to-hint latency.

## Project map

```text
frontend/pcm-worklet.js   Browser mic -> mono PCM16 LE, 16 kHz, 100 ms frames
frontend/api.js           Session storage + authenticated fetch helper
frontend/login.js/.html   Email/password login
frontend/signup.js/.html  Create an organization (first admin account)
frontend/app.js           WebSocket auth, audio sending, live transcript, hints
frontend/history.js/.html Call history, coaching analytics overview, search/filters, detail view
frontend/settings.js/.html WhatsApp recap, HubSpot CRM, Webhook nodes, Team invites, Playbooks
frontend/manifest.webmanifest Installable Mobile PWA manifest (standalone home-screen mode)
frontend/sw.js            Network-first PWA service worker for app-shell assets
mobile/App.js             React Native (Expo) companion app entry + 4-tab navigation
mobile/src/api.js         React Native REST + /ws/live WebSocket client
mobile/src/services/nativeCallBridge.js Background audio, floating hint overlay, call-end hook, WhatsApp share
mobile/src/screens/*.js   Live Call, Truecaller-style Post-Call Logger, History, and Settings screens
backend/app/auth.py       Password hashing + claims-based HMAC-signed session tokens
backend/app/auth_routes.py Signup/login/invite/me endpoints
backend/app/deps.py       FastAPI auth dependency (Bearer token -> claims)
backend/app/db.py         Async SQLAlchemy engine/session plumbing
backend/app/models.py     Organization / User / Membership / Call / Turn / Hint ORM models
backend/app/calls_routes.py Org-scoped call history endpoints (GET /api/calls, /api/calls/{id})
backend/app/main.py       WebSocket ingestion, latest-only hint queue, UI server
backend/app/deepgram.py   Deepgram streaming STT WebSocket adapter
backend/app/speech_sarvam.py Sarvam AI streaming STT adapter (Hindi/Hinglish), same interface as deepgram.py
backend/app/signals.py    Per-turn sentiment/intent tagging + live talk-time aggregation
backend/app/post_call.py  Post-call summary, coaching score, follow-up email draft
backend/app/crm.py        CRMProvider interface + HubSpot implementation
backend/app/crm_routes.py CRM connect/disconnect/settings endpoints
backend/app/playbook_routes.py Playbook library inspection + live markdown upsert/delete + hot-reload
backend/app/webhook_routes.py Generic signed-webhook node CRUD + test delivery endpoints
backend/app/crypto.py     At-rest encryption for stored third-party secrets (Fernet)
backend/app/knowledge.py Markdown chunking, lexical fallback, Chroma vector retrieval
backend/app/agent.py     Grounded 1-line instruction using LLM or demo rules
alembic/                 Database migrations (run `alembic upgrade head`)
scripts/init_env.py      Creates a private .env with fresh secrets
scripts/ingest.py        Embeds and indexes markdown playbooks into Chroma
playbooks/*.md           Illustrative documents; replace with approved company content
tests/                   Auth, retrieval, and WebSocket integration tests
```

## 1. Install

Use **Python 3.11 or 3.12** for broad ecosystem compatibility (especially Chroma). On macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python scripts/init_env.py
python -m alembic upgrade head
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1` instead of `source .venv/bin/activate`.

The initialization script creates a private `.env` with a fresh session-signing key and encryption key. **Do not commit `.env`.** The project archive includes only `.env.example`. By default the app stores data in a local SQLite file (`data/app.db`); set `DATABASE_URL` to a Postgres connection string for a real pilot deployment and re-run `alembic upgrade head` against it.

## 2. Launch a free text test (no provider keys)

```bash
python -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

Open **http://localhost:8000** — you'll be redirected to **/signup** the first time. Create your organization (you become its first admin), which logs you in automatically. Submit the prefilled text. You should see:

1. A `TEST INPUT` transcript line.
2. One suggestion labeled `DEMO RULE`.
3. Matching excerpts from the sample sales playbook.
4. Backend processing duration and a hint counter.

The demo rules use a few basic keyword patterns. There is no AI model involved in this free text-test path.

## 3. Enable real microphone transcription

Edit `.env` and add:

```ini
DEEPGRAM_API_KEY=your_real_key
```

Restart the FastAPI server, reconnect and use **Start microphone**. The browser requests microphone permission and sends **raw signed 16-bit little-endian PCM, 16 kHz, mono** in 100 ms binary frames. Deepgram receives `encoding=linear16&sample_rate=16000&channels=1` over its streaming WebSocket. Interim transcript text is rendered lightly; a finalized utterance triggers a hint.

**The Deepgram key remains server-side**; browser code receives only an ephemeral application WebSocket token. Use HTTPS/WSS for any non-local deployment. On ordinary HTTP origins that are not localhost, browsers deny microphone access.

If Deepgram is configured but OpenAI is not, live voice can be transcribed and hints remain in `DEMO RULE` mode, grounded by lexical retrieval.

## 4. Enable actual RAG + AI-generated hints

Add to `.env`:

```ini
OPENAI_API_KEY=your_real_key
OPENAI_HINT_MODEL=gpt-4o-mini
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
```

Replace illustrative content in `playbooks/` with **approved** company product sheets, objections, current pricing policies, and competitor guidance. Keep source files as UTF-8 `.md` for this MVP.

Build the vector index:

```bash
python -m scripts.ingest
```

Then **restart** FastAPI so it loads the Chroma index from `data/chroma/`. The dashboard should report `CHROMA EMBEDDINGS` and `AI GENERATED`. Ingest clears the previous Chroma collection and re-indexes all Markdown documents; this intentionally prevents stale playbook facts from remaining in the MVP.

If Chroma is missing or vector lookup fails, the app transparently falls back to **lexical-demo** retrieval. `GET /api/health` reports the configured retrieval mode. OpenAI failures do **not** silently impersonate AI responses; the UI displays an error.

**Data note:** When using Deepgram or OpenAI APIs, snippets of audio/transcription/playbooks are transmitted to those vendors to provide their service. Review the providers' retention/privacy settings and your customer agreements before using real call data. The app persists finalized transcript turns and generated hints (not raw audio) per call in the database, scoped to your organization — see **Call history** below.

## 5. Verify

```bash
python -m pytest -q
```

Run smoke checks:

```bash
curl http://localhost:8000/api/health
node --check frontend/app.js
node --check frontend/pcm-worklet.js
```

You can also test the endpoint with `TestClient` (see `tests/test_end_to_end.py`), which exercises: signup -> signed token -> authenticated WebSocket -> simulated utterance -> retrieval -> hint message.

## Accounts and teams

- `POST /api/auth/signup` — `{ organization_name, name, email, password }`. Creates a new organization and its first `admin` user, and returns a session token.
- `POST /api/auth/login` — `{ email, password }`. Returns a session token for an existing user (rate-limited to 10 attempts/minute/IP).
- `GET /api/auth/me` — `Authorization: Bearer <token>`. Returns the caller's user/organization/role.
- `GET /api/auth/team` — `Authorization: Bearer <token>`. Lists all members of the caller's organization (`admin`, `manager`, `rep`).
- `POST /api/auth/invite` — admin-only. `{ name, email, password, role }` (`role` is `admin`, `manager`, or `rep`) adds a teammate to the caller's organization (also available directly from **Settings → Team members**).

Session tokens are the same claims-based HMAC token described below, valid for `token_ttl_seconds` (12 hours by default), carrying `user_id`, `org_id`, and `role`. Changing or resetting a password **immediately revokes every existing session** (token versioning). Invites go out as emailed, single-use, 72-hour links (`/accept-invite?token=…`); without SMTP configured, the invite link is returned in the API response so an admin can hand it over manually. `POST /api/auth/forgot` → `POST /api/auth/reset` implement password reset with hashed, single-use, 60-minute tokens, and `PATCH /api/auth/me/password` lets a logged-in user change their own password.

## Call history and coaching analytics

Every `/ws/live` session and Twilio call is persisted as a `Call` row (with its finalized `Turn`s and generated `Hint`s), scoped to the organization in the caller's token. Live Twilio broadcasts and outbound mic audio are also strictly isolated to the owning organization.

- `GET /api/calls` — the caller's organization's most recent calls, with optional `?disposition=`, `?channel=` (`browser`, `twilio`, `mobile`), and `?q=` search filters.
- `GET /api/calls/analytics` — organization-wide coaching metrics (total/completed/consented calls, average coaching score, disposition breakdown, objection count, and per-rep summary).
- `GET /api/calls/{id}` — full detail: every turn (with sentiment and intent tags), every hint (with playbook sources and latency), and the post-call summary. 404s if the call belongs to a different organization.
- `POST /api/calls/{id}/summarize` — generates or refreshes the post-call summary, coaching score, disposition, and follow-up email draft on demand.
- `POST /api/calls/log-mobile` — Truecaller-style mobile post-call / field-meeting logger: records customer & rep turns (`channel="mobile"`), tags sentiment/intents, generates a grounded playbook hint + full post-call summary, and distributes externally when `consent_confirmed=true`.

Outbound Twilio calls (`POST /api/twilio/call`) now require a session token and tag the resulting call with the caller's `org_id`/`rep_user_id` via a custom `<Stream><Parameter>` in the TwiML, read back from the Media Stream's `start` event. An inbound call that never goes through that flow (e.g. a bare webhook hit without those parameters) is not persisted — only transcribed/hinted live, same as before.

## Real-time signals and post-call intelligence

- Every finalized utterance is tagged with a sentiment (`positive`/`neutral`/`negative`) and intents (`objection`, `pricing`, `buying_signal`, `discovery`) using fast keyword heuristics — no extra LLM call per turn, so it doesn't add latency to the hint pipeline. Broadcast live as `signals` WebSocket messages (talk-time ratio, sentiment counts, objection count) and shown on the dashboard.
- When a call ends, a post-call job generates a summary, a 0-100 coaching score, coaching notes, and a follow-up email draft — AI-generated when `OPENAI_API_KEY` is set, a deterministic rubric otherwise (same AI/rules-demo split used elsewhere). Surfaced in Call History (`GET /api/calls/{id}` includes `summary`).

## CRM integration

Connect HubSpot from **Settings** (admin-only) with a [Private App access token](https://developers.hubspot.com/docs/api/private-apps) (needs the `crm.objects.notes.write` scope) — no OAuth app registration required for this MVP integration. When connected with auto-push on, every call's post-call summary and follow-up draft is posted as a standalone HubSpot Note after the call ends. Tokens are encrypted at rest with `MASTER_ENCRYPTION_KEY` (`backend/app/crypto.py`, Fernet). Endpoints: `GET/POST /api/crm/status`, `/connect`, `/disconnect`, `PATCH /settings`. The `CRMProvider` interface (`backend/app/crm.py`) is provider-agnostic — Salesforce or a full OAuth flow can slot in later without changing callers.

## Consent, call disposition, and distribution (WhatsApp + webhooks)

Every call now requires the rep to confirm consent before it starts: a checkbox on the dashboard ("I've informed the other party this call is analyzed for sales coaching, and have their consent") gates both **Connect** and **Call phone**, sends a `confirm_consent` WebSocket message, and sets `Call.consent_confirmed_at`. Outbound Twilio calls carry the same flag through as a TwiML `<Parameter>`. **Nothing is pushed to a third party (CRM, WhatsApp, webhooks) for a call that wasn't consent-confirmed** — the summary still generates and is visible in Call History either way, it just stays internal. This is deliberately stricter than most "this call may be recorded" banners: see the design notes on India's DPDP Act 2023, which requires specific, informed, affirmative consent for commercial call processing, not a generic disclaimer.

Post-call analysis now also includes a **disposition** (`interested` / `not_interested` / `follow_up` / `no_decision` / `do_not_contact`) — AI-classified when OpenAI is configured, heuristic otherwise (`backend/app/post_call.py`), shown as a colored tag in Call History. Every delivered hint carries its database id so reps can mark it **Helpful / Not helpful** from the dashboard; feedback is stored per hint and rolled up as `hint_acceptance_rate` in `GET /api/calls/analytics` — the product's north-star coaching metric.

## Billing, plans, and call quotas

Every organization sits on a plan (`backend/app/billing.py`): **Pilot** (50 calls/month), **Growth** (500/month), or **Scale** (no limit), with an optional per-org `monthly_call_limit_override`. All three call entry points — browser `/ws/live`, Twilio `POST /api/twilio/call`, and the mobile logger `POST /api/calls/log-mobile` — enforce the meter against the current UTC month and fail gracefully (HTTP 402 / a WebSocket error+close) when it's exhausted. Admins can view usage and switch plans from **Settings → Billing** (`GET/POST /api/billing/*`); plan changes are manual until the Razorpay order + webhook flow is wired (keys are already provisioned in config).

## Twilio webhook authentication

`/api/twilio/twiml` validates Twilio's `X-Twilio-Signature` header (HMAC-SHA1 over the full URL + sorted params, `backend/app/twilio_security.py`) and rejects anything unsigned with HTTP 403, so a leaked URL can't be used to spin up Media Streams on your Twilio account. Disable only for local replay testing with `TWILIO_VALIDATE_SIGNATURE=false`. Behind a reverse proxy, the proxy must preserve the scheme/host Twilio signed (set `PUBLIC_BASE_URL` and forward `x-forwarded-*` headers).

## Email (invites & password resets)

Set `SMTP_HOST`/`SMTP_PORT`/`SMTP_USER`/`SMTP_PASSWORD`/`EMAIL_FROM` to send real transactional email. Unset `SMTP_HOST` is **dev mode**: message bodies (including invite/reset links) are written to the server log, and invite responses carry the link back to the admin UI so the flow completes without infrastructure.

## Deploying with Docker

```bash
docker compose up --build
```

runs the app (migrations applied automatically at boot) against a Postgres 16 service. Set `DATABASE_URL=postgresql+asyncpg://...` in `.env` for non-Docker deploys, and run `python -m alembic upgrade head` on release. GitHub Actions (`.github/workflows/ci.yml`) runs the full pytest suite and JS syntax checks on every push to `main`.

Two distribution channels, both gated on consent, both firing from the same point as the existing CRM push:

- **WhatsApp recap** — a rep opts in once from **Settings** (their own WhatsApp number + a toggle). After each consented call, a templated WhatsApp message (disposition, score, summary) sends to the rep's own number via Twilio's WhatsApp API — needs `TWILIO_WHATSAPP_FROM` and an approved `TWILIO_WHATSAPP_TEMPLATE_SID` (a one-time manual approval step through the Twilio/Meta console; the code path is complete and unit-tested but not runnable without your own approved template).
- **Webhook nodes** — the generic "plugin" mechanism (`backend/app/webhook_routes.py`, `/api/webhooks`). An admin adds one or more URLs in Settings; each gets its own secret. After a consented call, Sales Copilot POSTs a JSON payload (`event: "call.summary_ready"`, disposition, score, summary, follow-up draft) signed with `X-Signature-SHA256` (HMAC-SHA256 over the raw body) so the receiving end can verify it's really us. This is how Slack, Zapier, n8n, a spreadsheet, or anything else gets wired up without us building a dedicated integration for each one.

## Indian-language speech-to-text (Sarvam)

Set `STT_PROVIDER=sarvam` (plus `SARVAM_API_KEY`) to transcribe with [Sarvam AI](https://www.sarvam.ai/)'s `saaras:v3` streaming model in `codemix` mode instead of Deepgram, for both the browser-mic path and Twilio calls. Codemix output mixes Devanagari and Latin script the way Hindi/Hinglish speakers actually talk (`आपका solution थोड़ा expensive लग रहा है`), and the hint-generation prompt already understands it — verified live end-to-end (real Sarvam TTS audio in, transcribed, tagged, and answered with a grounded Hinglish hint from a real OpenAI call).

One real protocol difference from Deepgram: Sarvam's streaming API is VAD-segmented and only emits *finalized* transcripts per detected speech pause — there's no word-by-word interim/partial stream, so `transcript_interim` messages never fire on this path (the UI's live "…" preview simply stays empty; finals still arrive promptly). `backend/app/speech_sarvam.py` implements the same `open/send_audio/finalize/keepalive/close/consume` shape as `backend/app/deepgram.py`, so `main.py` treats both providers identically via `_open_mic_stt_stream()`/`get_or_open_stt()`. The Twilio path reuses the existing 8kHz mu-law → 16kHz PCM16 conversion (already needed for phone-audio playback) since Sarvam's streaming API only accepts 8/16kHz PCM, not mu-law.

`GET /api/health` reports the active `stt_provider`.

## WebSocket wire protocol

### Authenticate

Log in or sign up via the REST endpoints above to get a token, then open:

```javascript
new WebSocket('ws://localhost:8000/ws/live', ['copilot-v1', `auth.${token}`]);
```

Using the subprotocol avoids placing credentials in URL query strings; it is **not** a replacement for HTTPS. The backend validates the token and checks `Origin` against `ALLOWED_ORIGINS`. For deployments behind a reverse proxy, set this environment variable to your actual HTTPS origin (for example `https://your-app.example`).

### Browser to backend

| Message | Example | Meaning |
|---|---|---|
| Binary | PCM16 16k mono, 3200 bytes per 100 ms | Microphone frame |
| JSON | `{"type":"simulate_utterance","text":"We use Excel"}` | Text-only test |
| JSON | `{"type":"end_audio"}` | Flush pending transcription |

### Backend to browser

| `type` | Example fields |
|---|---|
| `ready` | `microphone_enabled`, `llm_enabled`, `retrieval_mode` |
| `transcript_interim` | `text` |
| `transcript_final` | `text`, `source` (`microphone` or `manual-test`), `sentiment`, `intents` |
| `signals` | `sentiment` (counts), `intents` (counts), `talk_time` (`rep_pct`/`customer_pct`) |
| `hint` | `text`, `method`, `sources`, `retrieval_mode`, `processing_ms` |
| `status` / `error` | `message` |

## Latency and stability design

- The audio worklet creates **100 ms frames**; the JS WebSocket checks `bufferedAmount` and reports backpressure rather than allowing unbounded buffering.
- Deepgram finalization/endpointing is currently set to **300 ms** silence with an utterance-end fallback.
- The backend **never sends interim fragments to the LLM**; only complete utterances trigger hint work.
- The worker queue has **one pending slot**; new completed utterances replace stale queued work, while an active model call finishes. Hints are throttled to a minimum of **1.5 seconds between starts**.
- Deepgram and the frontend share no API credentials. Deepgram frames are streamed through a separate backend WebSocket.
- No raw audio or recording files are ever persisted; only finalized transcript turns and generated hints are written to the database, per call. The in-memory deque is only a short rolling window used for prompting the LLM mid-call.

## Path to a true phone-call pilot

The microphone method is not a telephony tap. For live conversations with a remote customer:

1. Provision a legitimate consented call pathway with a telephony provider and geographic/regulatory support for the phone numbers involved.
2. Configure that provider's media streams endpoint and verify provider-signed webhook/handshake requests. Do **not** use the local demo access-code protocol as Twilio authentication.
3. Convert provider audio appropriately (for example 8 kHz mu-law) **or** configure STT for that exact encoding/sample rate; never label mu-law as PCM16.
4. Preserve customer/representative track identities, and trigger recommendations mainly from the **customer** track (the current browser MVP labels only local mic input).
5. Add session-to-user mapping, consent notice, privacy/retention rules, reconnect/retry handling, encrypted storage if storing transcripts, monitoring, and proper user authentication (SSO/OAuth) before a production rollout.

## Limitations / next improvements

- No browser-based calling or remote participant audio capture.
- Accounts now use real email/password + per-organization roles (`admin`/`manager`/`rep`), but there's no SSO/OAuth, password reset, or invite email yet — add those before a wider rollout.
- Simple lexical fallback and rule-based demo are intentionally less sophisticated than vector RAG + LLM.
- PDF/DOCX playbook parsing, document version approvals, source-level citations, multi-tenant indexing, redaction, sensitive-entity filters, vendor retention agreements and telemetry are not yet implemented.
- Mobile browser behavior varies: active mic and WebSockets can be interrupted when the page is backgrounded, the device locks, or another app uses the microphone.
- Full latency load tests and provider integration tests require real provider credentials and representative audio, which are not bundled.

## API and browser references

- Deepgram streaming: https://developers.deepgram.com/reference/speech-to-text/listen-streaming
- Deepgram encoding: https://developers.deepgram.com/docs/encoding
- OpenAI embeddings: https://developers.openai.com/api/docs/guides/embeddings
- Chroma persistent collections: https://docs.trychroma.com/reference/python
- MDN getUserMedia: https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia
- MDN AudioWorklet: https://developer.mozilla.org/en-US/docs/Web/API/AudioWorkletProcessor

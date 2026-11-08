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
frontend/index.html       Responsive dashboard
frontend/style.css        Dashboard styling
backend/app/auth.py       Password hashing + claims-based HMAC-signed session tokens
backend/app/auth_routes.py Signup/login/invite/me endpoints
backend/app/deps.py       FastAPI auth dependency (Bearer token -> claims)
backend/app/db.py         Async SQLAlchemy engine/session plumbing
backend/app/models.py     Organization / User / Membership / Call / Turn / Hint ORM models
backend/app/calls_routes.py Org-scoped call history endpoints (GET /api/calls, /api/calls/{id})
backend/app/main.py       WebSocket ingestion, latest-only hint queue, UI server
backend/app/deepgram.py   Deepgram streaming STT WebSocket adapter
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
- `POST /api/auth/invite` — admin-only. `{ name, email, password, role }` (`role` is `admin`, `manager`, or `rep`) adds a teammate to the caller's organization. There's no outbound email yet; share the password with the invitee directly.

Session tokens are the same claims-based HMAC token described below, valid for `token_ttl_seconds` (12 hours by default), carrying `user_id`, `org_id`, and `role`.

## Call history

Every `/ws/live` session and Twilio call is persisted as a `Call` row (with its finalized `Turn`s and generated `Hint`s), scoped to the organization in the caller's token.

- `GET /api/calls` — the caller's organization's most recent calls (summary: channel, start/end time, turn/hint counts).
- `GET /api/calls/{id}` — full detail: every turn and hint for that call. 404s if the call belongs to a different organization.

Outbound Twilio calls (`POST /api/twilio/call`) now require a session token and tag the resulting call with the caller's `org_id`/`rep_user_id` via a custom `<Stream><Parameter>` in the TwiML, read back from the Media Stream's `start` event. An inbound call that never goes through that flow (e.g. a bare webhook hit without those parameters) is not persisted — only transcribed/hinted live, same as before.

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
| `transcript_final` | `text`, `source` (`microphone` or `manual-test`) |
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

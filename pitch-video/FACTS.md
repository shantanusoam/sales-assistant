# FACTS — SalesCopilot Launch Film

| # | Claim as shown (screen / voice) | Source (URL or file) | Quoted wording | Date |
|---|---|---|---|---|
| 1 | Streaming STT via Deepgram (`nova-3`) and Sarvam AI (`saaras:v3` codemix) | `backend/app/config.py`, `backend/app/speech_sarvam.py` | `MODEL = "saaras:v3"`, `MODE = "codemix"`, `deepgram_model: "nova-3"` | 2026-11-10 |
| 2 | Playbook RAG grounds hints using ChromaDB embeddings + lexical fallback | `backend/app/knowledge.py`, `backend/app/agent.py` | `self.mode = "chroma-embeddings"`, `self.mode = "lexical-demo"` | 2026-11-10 |
| 3 | External distribution (CRM, WhatsApp, Webhooks) is gated on per-call affirmative consent (`DPDP Consent`) | `backend/app/main.py` lines 168–171 | `if call and call.organization_id and call.consent_confirmed_at:` | 2026-11-10 |
| 4 | Mobile support via installable PWA (`manifest.webmanifest` + Wake Lock) and React Native companion app (`mobile/`) | `frontend/manifest.webmanifest`, `mobile/app.json` | `"display": "standalone"`, `UIBackgroundModes: ["audio", "voip"]` | 2026-11-10 |
| 5 | Outgoing webhooks signed with `HMAC-SHA256` (`X-Signature-SHA256`) and CRM tokens encrypted with Fernet | `backend/app/main.py`, `backend/app/crypto.py` | `hmac.new(node.secret.encode(), body, hashlib.sha256).hexdigest()` | 2026-11-10 |

## Measured values
| Value | Method | File |
|---|---|---|
| VO L1–L6 durations & word timestamps | ElevenLabs `/v1/text-to-speech/{voice_id}/with-timestamps` + `ffprobe` | `pitch-video/audio/vo_meta.json` |

## Illustrative (labelled on screen as `Example data`)
- Simulated Hinglish customer utterance (`"आपका solution थोड़ा expensive लग रहा है, अभी हमारा budget tight है।"`), Talk-Time split (`36% Rep / 64% Customer`), and Post-Call Coaching Score (`85 / 100`): illustrative demo call values, explicitly labelled `Example data` on the Bento UI header.

## Not claimed
- No customer logos, third-party endorsements, or unverified conversion multipliers are claimed.

"""Create a fresh local .env, without shipping real secrets in the project archive."""
from pathlib import Path
import secrets

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / ".env"
if TARGET.exists():
    raise SystemExit(".env already exists; it was not overwritten.")
access = secrets.token_urlsafe(18)
signing = secrets.token_urlsafe(48)
content = (ROOT / ".env.example").read_text(encoding="utf-8")
content = content.replace("REPLACE_WITH_GENERATED_DEMO_ACCESS_CODE", access)
content = content.replace("REPLACE_WITH_GENERATED_SESSION_SIGNING_KEY", signing)
TARGET.write_text(content, encoding="utf-8")
try:
    TARGET.chmod(0o600)
except OSError:
    pass
print("Created .env. Your local demo access code (keep private):", access)
print("Set DEEPGRAM_API_KEY for microphone transcription, and OPENAI_API_KEY for vector RAG and AI hints.")

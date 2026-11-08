"""Create a fresh local .env, without shipping real secrets in the project archive."""
from pathlib import Path
import secrets

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / ".env"
if TARGET.exists():
    raise SystemExit(".env already exists; it was not overwritten.")
signing = secrets.token_urlsafe(48)
encryption = secrets.token_urlsafe(32)
content = (ROOT / ".env.example").read_text(encoding="utf-8")
content = content.replace("REPLACE_WITH_GENERATED_SESSION_SIGNING_KEY", signing)
content = content.replace("REPLACE_WITH_GENERATED_MASTER_ENCRYPTION_KEY", encryption)
TARGET.write_text(content, encoding="utf-8")
try:
    TARGET.chmod(0o600)
except OSError:
    pass
(ROOT / "data").mkdir(exist_ok=True)
print("Created .env with a fresh session signing key and encryption key.")
print("Next: python -m alembic upgrade head, then start the server and visit /signup to create your organization.")
print("Set DEEPGRAM_API_KEY for microphone transcription, and OPENAI_API_KEY for vector RAG and AI hints.")

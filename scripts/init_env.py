"""Create or update a local .env with required secret keys without overwriting existing values."""
from pathlib import Path
import secrets

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / ".env"
(ROOT / "data").mkdir(exist_ok=True)

if not TARGET.exists():
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
    print("Created .env with a fresh session signing key and encryption key.")
else:
    text = TARGET.read_text(encoding="utf-8")
    updated = False
    for key_name, nbytes, placeholder in (
        ("SESSION_SIGNING_KEY", 48, "REPLACE_WITH_GENERATED_SESSION_SIGNING_KEY"),
        ("MASTER_ENCRYPTION_KEY", 32, "REPLACE_WITH_GENERATED_MASTER_ENCRYPTION_KEY"),
    ):
        existing_lines = [line for line in text.splitlines() if line.startswith(f"{key_name}=")]
        val = existing_lines[0].split("=", 1)[1].strip() if existing_lines else ""
        if not val or val == placeholder:
            fresh = secrets.token_urlsafe(nbytes)
            if existing_lines:
                text = "\n".join(
                    f"{key_name}={fresh}" if line.startswith(f"{key_name}=") else line
                    for line in text.splitlines()
                ) + "\n"
            else:
                text = text.rstrip() + f"\n{key_name}={fresh}\n"
            updated = True
    if updated:
        TARGET.write_text(text, encoding="utf-8")
        print("Backfilled missing secret keys in existing .env without overwriting existing configuration.")
    else:
        print(".env already exists and has all required secret keys; nothing overwritten.")

print("Next: python -m alembic upgrade head, then start the server and visit /signup to create your organization.")
print("Set DEEPGRAM_API_KEY for microphone transcription, and OPENAI_API_KEY for vector RAG and AI hints.")

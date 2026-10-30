"""Runtime configuration. Never place credentials in frontend code."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


@dataclass(frozen=True)
class Settings:
    demo_access_code: str = field(default_factory=lambda: _env("DEMO_ACCESS_CODE"))
    session_signing_key: str = field(default_factory=lambda: _env("SESSION_SIGNING_KEY"))
    token_ttl_seconds: int = 600
    allowed_origins: tuple[str, ...] = field(default_factory=lambda: tuple(
        x.strip() for x in _env("ALLOWED_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000").split(",") if x.strip()
    ))
    deepgram_api_key: str = field(default_factory=lambda: _env("DEEPGRAM_API_KEY"))
    deepgram_model: str = field(default_factory=lambda: _env("DEEPGRAM_MODEL", "nova-3"))
    deepgram_language: str = field(default_factory=lambda: _env("DEEPGRAM_LANGUAGE", "multi"))
    openai_api_key: str = field(default_factory=lambda: _env("OPENAI_API_KEY"))
    openai_hint_model: str = field(default_factory=lambda: _env("OPENAI_HINT_MODEL", "gpt-4o-mini"))
    openai_embedding_model: str = field(default_factory=lambda: _env("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"))
    twilio_account_sid: str = field(default_factory=lambda: _env("TWILIO_ACCOUNT_SID"))
    twilio_auth_token: str = field(default_factory=lambda: _env("TWILIO_AUTH_TOKEN"))
    twilio_phone_number: str = field(default_factory=lambda: _env("TWILIO_PHONE_NUMBER"))
    twilio_default_to: str = field(default_factory=lambda: _env("TWILIO_DEFAULT_TO"))
    public_base_url: str = field(default_factory=lambda: _env("PUBLIC_BASE_URL"))
    playbook_dir: Path = ROOT / "playbooks"
    chroma_dir: Path = ROOT / "data" / "chroma"
    hint_cooldown_seconds: float = 1.5
    max_audio_bytes_per_frame: int = 32000  # <= 1 second at 16 kHz PCM16

    @property
    def configured(self) -> bool:
        return (len(self.demo_access_code) >= 12
                and len(self.session_signing_key) >= 32
                and not self.demo_access_code.startswith("REPLACE_WITH_")
                and not self.session_signing_key.startswith("REPLACE_WITH_"))

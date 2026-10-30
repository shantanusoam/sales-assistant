"""Short-lived HMAC tokens for the local prototype, transmitted as a WS subprotocol."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time

from .config import Settings


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def check_access_code(user_code: str, settings: Settings) -> bool:
    return settings.configured and hmac.compare_digest(user_code, settings.demo_access_code)


def issue_token(settings: Settings, now: int | None = None) -> str:
    if not settings.configured:
        raise ValueError("Run python scripts/init_env.py to create demo credentials.")
    issued = int(time.time()) if now is None else now
    payload = {"iat": issued, "exp": issued + settings.token_ttl_seconds, "jti": secrets.token_hex(12)}
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    signature = _b64(hmac.new(settings.session_signing_key.encode(), body.encode(), hashlib.sha256).digest())
    return body + "." + signature


def verify_token(token: str, settings: Settings, now: int | None = None) -> bool:
    if not settings.configured or len(token) > 4096:
        return False
    try:
        body, signature = token.split(".", 1)
        if not body or not signature:
            return False
        expected = _b64(hmac.new(settings.session_signing_key.encode(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            return False
        payload = json.loads(_decode(body))
        current = int(time.time()) if now is None else now
        return (isinstance(payload["iat"], int)
                and isinstance(payload["exp"], int)
                and payload["iat"] - 10 <= current < payload["exp"]
                and payload["exp"] - payload["iat"] <= settings.token_ttl_seconds)
    except (ValueError, KeyError, TypeError, UnicodeError):
        return False


def extract_ws_token(header: str) -> str:
    protocols = [part.strip() for part in header.split(",")]
    if "copilot-v1" not in protocols:
        return ""
    auth = [part[5:] for part in protocols if part.startswith("auth.")]
    return auth[0] if len(auth) == 1 else ""

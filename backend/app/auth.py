"""Password hashing and short-lived HMAC-signed session tokens, transmitted as a WS subprotocol."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time

import bcrypt

from .config import Settings


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except (ValueError, TypeError):
        return False


def issue_token(settings: Settings, claims: dict, ttl_seconds: int | None = None, now: int | None = None) -> str:
    """Sign arbitrary claims (e.g. user_id/org_id/role) into a short-lived token."""
    if not settings.configured:
        raise ValueError("Run python scripts/init_env.py to create a session signing key.")
    issued = int(time.time()) if now is None else now
    ttl = settings.token_ttl_seconds if ttl_seconds is None else ttl_seconds
    payload = {**claims, "iat": issued, "exp": issued + ttl, "jti": secrets.token_hex(12)}
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    signature = _b64(hmac.new(settings.session_signing_key.encode(), body.encode(), hashlib.sha256).digest())
    return body + "." + signature


def verify_token(token: str, settings: Settings, now: int | None = None) -> dict | None:
    """Return the signed claims if the token is valid and unexpired, else None."""
    if not settings.configured or len(token) > 4096:
        return None
    try:
        body, signature = token.split(".", 1)
        if not body or not signature:
            return None
        expected = _b64(hmac.new(settings.session_signing_key.encode(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            return None
        payload = json.loads(_decode(body))
        current = int(time.time()) if now is None else now
        if not (isinstance(payload["iat"], int) and isinstance(payload["exp"], int)):
            return None
        if not (payload["iat"] - 10 <= current < payload["exp"]):
            return None
        return payload
    except (ValueError, KeyError, TypeError, UnicodeError):
        return None


def extract_ws_token(header: str) -> str:
    protocols = [part.strip() for part in header.split(",")]
    if "copilot-v1" not in protocols:
        return ""
    auth = [part[5:] for part in protocols if part.startswith("auth.")]
    return auth[0] if len(auth) == 1 else ""

"""At-rest encryption for third-party secrets (CRM tokens, etc.) using the app's
MASTER_ENCRYPTION_KEY. Fernet needs a 32-byte urlsafe-base64 key; we derive one
from the configured key via SHA-256 so any sufficiently random string works,
not just a key generated in Fernet's own format.
"""
from __future__ import annotations

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from .config import Settings


@lru_cache(maxsize=4)
def _fernet(master_key: str) -> Fernet:
    digest = hashlib.sha256(master_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(plaintext: str, settings: Settings) -> str:
    if not settings.master_encryption_key:
        raise ValueError("MASTER_ENCRYPTION_KEY is not configured; run scripts/init_env.py.")
    return _fernet(settings.master_encryption_key).encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(ciphertext: str, settings: Settings) -> str:
    if not settings.master_encryption_key:
        raise ValueError("MASTER_ENCRYPTION_KEY is not configured; run scripts/init_env.py.")
    try:
        return _fernet(settings.master_encryption_key).decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Stored secret could not be decrypted (wrong or rotated MASTER_ENCRYPTION_KEY).") from exc

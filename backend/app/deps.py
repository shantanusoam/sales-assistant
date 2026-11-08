"""FastAPI-specific request dependencies (kept out of auth.py so that module stays framework-free)."""
from __future__ import annotations

from collections.abc import Callable

from fastapi import HTTPException, Request

from .auth import verify_token
from .config import Settings


def build_current_claims_dependency(settings: Settings) -> Callable[[Request], dict]:
    """Returns a FastAPI dependency that extracts and verifies a `Bearer <token>` header."""

    async def current_claims(request: Request) -> dict:
        header = request.headers.get("authorization", "")
        token = header[7:].strip() if header.lower().startswith("bearer ") else ""
        claims = verify_token(token, settings) if token else None
        if not claims:
            raise HTTPException(401, "Missing or invalid Authorization token.")
        return claims

    return current_claims

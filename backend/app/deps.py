"""FastAPI-specific request dependencies (kept out of auth.py so that module stays framework-free)."""
from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import verify_token
from .config import Settings
from .models import User


def _revoked(claims: dict, user: User | None) -> bool:
    """A token is revoked when its `tv` (token version) claim no longer matches the
    user's current value — i.e. any password change/reset invalidated it."""
    if user is None:
        return True
    return claims.get("tv", 0) != user.token_version


def build_current_claims_dependency(settings: Settings, get_db=None) -> Callable[[Request], dict]:
    """Returns a FastAPI dependency that extracts and verifies a `Bearer <token>` header.

    When get_db is provided, every authed request additionally checks the user's
    current token_version, so password changes revoke existing sessions immediately.
    """

    if get_db is None:

        async def current_claims(request: Request) -> dict:
            header = request.headers.get("authorization", "")
            token = header[7:].strip() if header.lower().startswith("bearer ") else ""
            claims = verify_token(token, settings) if token else None
            if not claims:
                raise HTTPException(401, "Missing or invalid Authorization token.")
            return claims

        return current_claims

    async def current_claims(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
        header = request.headers.get("authorization", "")
        token = header[7:].strip() if header.lower().startswith("bearer ") else ""
        claims = verify_token(token, settings) if token else None
        if not claims:
            raise HTTPException(401, "Missing or invalid Authorization token.")
        user = await db.scalar(select(User).where(User.id == claims.get("user_id", "")))
        if _revoked(claims, user):
            raise HTTPException(401, "Session expired. Please log in again.")
        return claims

    return current_claims

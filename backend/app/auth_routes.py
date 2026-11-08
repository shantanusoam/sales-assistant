"""Signup/login/invite endpoints and the org-scoped /api/me lookup."""
from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import hash_password, issue_token, verify_password
from .config import Settings
from .deps import build_current_claims_dependency
from .models import Membership, Organization, User

VALID_ROLES = {"admin", "manager", "rep"}


class SignupRequest(BaseModel):
    organization_name: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class InviteRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    role: str = Field(default="rep")


def _session_payload(settings: Settings, user: User, org: Organization, role: str) -> dict:
    claims = {"user_id": user.id, "org_id": org.id, "role": role}
    return {
        "token": issue_token(settings, claims),
        "expires_in": settings.token_ttl_seconds,
        "user": {"id": user.id, "email": user.email, "name": user.name},
        "organization": {"id": org.id, "name": org.name},
        "role": role,
    }


def build_auth_router(settings: Settings, get_db) -> APIRouter:
    router = APIRouter(prefix="/api/auth", tags=["auth"])
    require_auth = build_current_claims_dependency(settings)
    failed_logins: dict[str, deque[float]] = defaultdict(deque)

    @router.post("/signup")
    async def signup(payload: SignupRequest, db: AsyncSession = Depends(get_db)) -> dict:
        existing = await db.scalar(select(User).where(User.email == payload.email.lower()))
        if existing is not None:
            raise HTTPException(409, "An account with that email already exists.")
        org = Organization(name=payload.organization_name.strip())
        user = User(email=payload.email.lower(), name=payload.name.strip(), password_hash=hash_password(payload.password))
        membership = Membership(role="admin")
        membership.user = user
        membership.organization = org
        db.add_all([org, user, membership])
        await db.commit()
        return _session_payload(settings, user, org, "admin")

    @router.post("/login")
    async def login(payload: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)) -> dict:
        ip = request.client.host if request.client else "unknown"
        attempts = failed_logins[ip]
        now = time.monotonic()
        while attempts and attempts[0] < now - 60:
            attempts.popleft()
        if len(attempts) >= 10:
            raise HTTPException(429, "Too many login attempts; try again later.")
        user = await db.scalar(select(User).where(User.email == payload.email.lower()))
        if user is None or not verify_password(payload.password, user.password_hash):
            attempts.append(now)
            raise HTTPException(401, "Invalid email or password.")
        membership = await db.scalar(
            select(Membership).where(Membership.user_id == user.id).order_by(Membership.created_at)
        )
        if membership is None:
            raise HTTPException(403, "This account is not attached to an organization.")
        org = await db.get(Organization, membership.organization_id)
        return _session_payload(settings, user, org, membership.role)

    @router.get("/me")
    async def me(claims: dict = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> dict:
        user = await db.get(User, claims["user_id"])
        org = await db.get(Organization, claims["org_id"])
        if user is None or org is None:
            raise HTTPException(404, "Account no longer exists.")
        return {
            "user": {"id": user.id, "email": user.email, "name": user.name},
            "organization": {"id": org.id, "name": org.name},
            "role": claims["role"],
        }

    @router.post("/invite")
    async def invite(payload: InviteRequest, claims: dict = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> dict:
        if claims["role"] != "admin":
            raise HTTPException(403, "Only an org admin can invite teammates.")
        if payload.role not in VALID_ROLES:
            raise HTTPException(400, f"role must be one of {sorted(VALID_ROLES)}.")
        org = await db.get(Organization, claims["org_id"])
        existing = await db.scalar(select(User).where(User.email == payload.email.lower()))
        if existing is not None:
            dupe = await db.scalar(
                select(Membership).where(Membership.user_id == existing.id, Membership.organization_id == org.id)
            )
            if dupe is not None:
                raise HTTPException(409, "That person is already a member of this organization.")
            user = existing
        else:
            user = User(email=payload.email.lower(), name=payload.name.strip(), password_hash=hash_password(payload.password))
            db.add(user)
        membership = Membership(role=payload.role)
        membership.user = user
        membership.organization = org
        db.add(membership)
        await db.commit()
        return {"user": {"id": user.id, "email": user.email, "name": user.name}, "role": payload.role}

    return router

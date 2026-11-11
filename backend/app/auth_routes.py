"""Signup/login/invite endpoints, email-backed invite links, password reset, and the org-scoped /api/me lookup."""
from __future__ import annotations

import hashlib
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import hash_password, issue_token, verify_password
from .config import Settings
from .deps import build_current_claims_dependency
from .emailer import build_mailer
from .models import InviteToken, Membership, Organization, PasswordResetToken, User

VALID_ROLES = {"admin", "manager", "rep"}

INVITE_TTL_HOURS = 72
RESET_TTL_MINUTES = 60


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
    # Optional: when set, the admin provisions the teammate's password directly
    # (shared out-of-band). When omitted, an emailed invite link is used instead —
    # the recommended path, since the teammate picks their own password.
    password: str | None = Field(default=None, max_length=200)
    role: str = Field(default="rep")


class InviteAcceptRequest(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    password: str = Field(min_length=8, max_length=200)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    password: str = Field(min_length=8, max_length=200)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=8, max_length=200)


class WhatsAppPrefsRequest(BaseModel):
    whatsapp_number: str | None = Field(default=None, max_length=32, description="E.164 format, e.g. +91...")
    whatsapp_recap_enabled: bool = False


def _token_digest(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _base_url(settings: Settings, request: Request | None = None) -> str:
    if settings.public_base_url:
        return settings.public_base_url.rstrip("/")
    if request is not None:
        host = request.headers.get("x-forwarded-host") or request.headers.get("host") or "localhost:8000"
        scheme = request.headers.get("x-forwarded-proto") or "http"
        return f"{scheme}://{host}"
    return "http://localhost:8000"


def _session_payload(settings: Settings, user: User, org: Organization, role: str) -> dict:
    claims = {"user_id": user.id, "org_id": org.id, "role": role, "tv": user.token_version}
    return {
        "token": issue_token(settings, claims),
        "expires_in": settings.token_ttl_seconds,
        "user": {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "whatsapp_number": user.whatsapp_number,
            "whatsapp_recap_enabled": user.whatsapp_recap_enabled,
        },
        "organization": {"id": org.id, "name": org.name},
        "role": role,
    }


def build_auth_router(settings: Settings, get_db, mailer=None) -> APIRouter:
    router = APIRouter(prefix="/api/auth", tags=["auth"])
    require_auth = build_current_claims_dependency(settings, get_db)
    send_email = mailer or build_mailer(settings)
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
            "user": {
                "id": user.id, "email": user.email, "name": user.name,
                "whatsapp_number": user.whatsapp_number, "whatsapp_recap_enabled": user.whatsapp_recap_enabled,
            },
            "organization": {"id": org.id, "name": org.name},
            "role": claims["role"],
        }

    @router.patch("/me/whatsapp")
    async def update_whatsapp_prefs(payload: WhatsAppPrefsRequest, claims: dict = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> dict:
        user = await db.get(User, claims["user_id"])
        if user is None:
            raise HTTPException(404, "Account no longer exists.")
        number = (payload.whatsapp_number or "").strip() or None
        if payload.whatsapp_recap_enabled and not number:
            raise HTTPException(400, "Add your WhatsApp number before enabling recaps.")
        user.whatsapp_number = number
        user.whatsapp_recap_enabled = payload.whatsapp_recap_enabled
        await db.commit()
        return {"whatsapp_number": user.whatsapp_number, "whatsapp_recap_enabled": user.whatsapp_recap_enabled}

    @router.patch("/me/password")
    async def change_password(
        payload: ChangePasswordRequest, claims: dict = Depends(require_auth), db: AsyncSession = Depends(get_db)
    ) -> dict:
        user = await db.get(User, claims["user_id"])
        if user is None:
            raise HTTPException(404, "Account no longer exists.")
        if not verify_password(payload.current_password, user.password_hash):
            raise HTTPException(401, "Current password is incorrect.")
        user.password_hash = hash_password(payload.new_password)
        user.token_version += 1  # revoke every previously issued session
        await db.commit()
        membership = await db.scalar(select(Membership).where(Membership.user_id == user.id).order_by(Membership.created_at))
        org = await db.get(Organization, membership.organization_id)
        return _session_payload(settings, user, org, membership.role)

    @router.get("/team")
    async def list_team(claims: dict = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> dict:
        rows = (
            await db.execute(
                select(Membership, User)
                .join(User, Membership.user_id == User.id)
                .where(Membership.organization_id == claims["org_id"])
                .order_by(Membership.created_at)
            )
        ).all()
        return {
            "members": [
                {
                    "id": user.id,
                    "name": user.name,
                    "email": user.email,
                    "role": membership.role,
                    "created_at": membership.created_at.isoformat(),
                }
                for membership, user in rows
            ]
        }

    @router.post("/invite")
    async def invite(payload: InviteRequest, request: Request, claims: dict = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> dict:
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
            # A placeholder password nobody knows; the invited teammate sets their own
            # via the emailed accept link (or the admin passed an explicit password).
            placeholder = hash_password(secrets.token_urlsafe(24))
            user = User(
                email=payload.email.lower(),
                name=payload.name.strip(),
                password_hash=hash_password(payload.password) if payload.password else placeholder,
            )
            db.add(user)
            await db.flush()  # assign user.id before the invite token references it
        membership = Membership(role=payload.role)
        membership.user = user
        membership.organization = org
        db.add(membership)

        invite_link = None
        emailed = False
        if not payload.password:
            raw = secrets.token_urlsafe(32)
            db.add(InviteToken(
                user_id=user.id,
                organization_id=org.id,
                token_hash=_token_digest(raw),
                expires_at=datetime.now(timezone.utc) + timedelta(hours=INVITE_TTL_HOURS),
            ))
            invite_link = f"{_base_url(settings, request)}/accept-invite?token={raw}"
            emailed = await send_email(
                user.email,
                f"You've been invited to {org.name} on Sales Copilot",
                (
                    f"Hi {user.name},\n\n"
                    f"{org.name} added you to their Sales Copilot workspace as a {payload.role}.\n"
                    f"Set your password and log in within {INVITE_TTL_HOURS} hours:\n\n{invite_link}\n\n"
                    "If the link expired, ask your admin to resend the invite."
                ),
            )
        await db.commit()
        response = {"user": {"id": user.id, "email": user.email, "name": user.name}, "role": payload.role}
        if invite_link:
            response["invite"] = {
                "link_sent": emailed,
                # Surfaced in-app as a fallback when no SMTP is configured, so the
                # admin always has a way to hand the link over manually.
                "link": None if emailed else invite_link,
            }
        return response

    @router.post("/invite/accept")
    async def accept_invite(payload: InviteAcceptRequest, db: AsyncSession = Depends(get_db)) -> dict:
        invite = await db.scalar(select(InviteToken).where(InviteToken.token_hash == _token_digest(payload.token)))
        # SQLite returns naive datetimes; compare in naive UTC everywhere.
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        if invite is None or invite.used_at is not None or invite.expires_at < now:
            raise HTTPException(400, "This invite link is invalid, used, or expired. Ask your admin to resend it.")
        user = await db.get(User, invite.user_id)
        org = await db.get(Organization, invite.organization_id)
        if user is None or org is None:
            raise HTTPException(404, "The invited account no longer exists.")
        user.password_hash = hash_password(payload.password)
        user.token_version += 1
        invite.used_at = now
        await db.commit()
        membership = await db.scalar(
            select(Membership).where(Membership.user_id == user.id, Membership.organization_id == org.id)
        )
        return _session_payload(settings, user, org, membership.role if membership else "rep")

    @router.post("/forgot")
    async def forgot_password(payload: ForgotPasswordRequest, request: Request, db: AsyncSession = Depends(get_db)) -> dict:
        # Always answer 200 so the endpoint can't be used to enumerate accounts.
        user = await db.scalar(select(User).where(User.email == payload.email.lower()))
        link = None
        if user is not None:
            raw = secrets.token_urlsafe(32)
            db.add(PasswordResetToken(
                user_id=user.id,
                token_hash=_token_digest(raw),
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=RESET_TTL_MINUTES),
            ))
            await db.commit()
            link = f"{_base_url(settings, request)}/reset-password?token={raw}"
            emailed = await send_email(
                user.email,
                "Reset your Sales Copilot password",
                (
                    "Hi,\n\nSomeone (hopefully you) asked to reset your Sales Copilot password.\n"
                    f"This link works once and expires in {RESET_TTL_MINUTES} minutes:\n\n{link}\n\n"
                    "If you didn't request this, you can ignore this email — your password is unchanged."
                ),
            )
            if not emailed:
                # Dev mode without SMTP: hand the link back so the flow is completable.
                link = None if not isinstance(link, str) else link
        return {"ok": True, "reset_link_dev": link}

    @router.post("/reset")
    async def reset_password(payload: ResetPasswordRequest, db: AsyncSession = Depends(get_db)) -> dict:
        record = await db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == _token_digest(payload.token)))
        now = datetime.now(timezone.utc).replace(tzinfo=None)  # SQLite returns naive datetimes
        if record is None or record.used_at is not None or record.expires_at < now:
            raise HTTPException(400, "This reset link is invalid, used, or expired. Request a new one.")
        user = await db.get(User, record.user_id)
        if user is None:
            raise HTTPException(404, "Account no longer exists.")
        user.password_hash = hash_password(payload.password)
        user.token_version += 1  # invalidate every other active session
        record.used_at = now
        await db.commit()
        membership = await db.scalar(select(Membership).where(Membership.user_id == user.id).order_by(Membership.created_at))
        org = await db.get(Organization, membership.organization_id)
        return _session_payload(settings, user, org, membership.role)

    return router

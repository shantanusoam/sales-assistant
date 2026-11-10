"""Org-scoped CRM connection endpoints: connect/disconnect, status, auto-push toggle."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings
from .crm import CRMError, PROVIDERS, build_provider
from .crypto import encrypt_secret
from .models import CRMConnection


class ConnectRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=40)
    token: str = Field(min_length=1, max_length=4000)


class SettingsRequest(BaseModel):
    auto_push: bool


def build_crm_router(settings: Settings, get_db, require_auth) -> APIRouter:
    router = APIRouter(prefix="/api/crm", tags=["crm"])

    def require_admin(claims: dict) -> None:
        if claims["role"] != "admin":
            raise HTTPException(403, "Only an org admin can manage the CRM connection.")

    @router.get("/status")
    async def status(claims: dict = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> dict:
        conn = await db.scalar(select(CRMConnection).where(CRMConnection.organization_id == claims["org_id"]))
        if not conn:
            return {"connected": False, "providers": list(PROVIDERS)}
        return {
            "connected": True,
            "provider": conn.provider,
            "auto_push": conn.auto_push,
            "connected_at": conn.connected_at.isoformat(),
            "providers": list(PROVIDERS),
        }

    @router.post("/connect")
    async def connect(payload: ConnectRequest, claims: dict = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> dict:
        require_admin(claims)
        if payload.provider not in PROVIDERS:
            raise HTTPException(400, f"Unknown provider. Supported: {', '.join(PROVIDERS)}.")
        provider = build_provider(payload.provider, payload.token)
        try:
            await provider.test_connection()
        except CRMError as exc:
            raise HTTPException(400, str(exc)) from exc

        existing = await db.scalar(select(CRMConnection).where(CRMConnection.organization_id == claims["org_id"]))
        try:
            encrypted = encrypt_secret(payload.token, settings)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if existing:
            existing.provider = payload.provider
            existing.encrypted_token = encrypted
        else:
            db.add(CRMConnection(organization_id=claims["org_id"], provider=payload.provider, encrypted_token=encrypted))
        await db.commit()
        return {"connected": True, "provider": payload.provider}

    @router.post("/disconnect")
    async def disconnect(claims: dict = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> dict:
        require_admin(claims)
        conn = await db.scalar(select(CRMConnection).where(CRMConnection.organization_id == claims["org_id"]))
        if conn:
            await db.delete(conn)
            await db.commit()
        return {"connected": False}

    @router.patch("/settings")
    async def update_settings(payload: SettingsRequest, claims: dict = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> dict:
        require_admin(claims)
        conn = await db.scalar(select(CRMConnection).where(CRMConnection.organization_id == claims["org_id"]))
        if not conn:
            raise HTTPException(404, "No CRM is connected for this organization.")
        conn.auto_push = payload.auto_push
        await db.commit()
        return {"connected": True, "auto_push": conn.auto_push}

    return router

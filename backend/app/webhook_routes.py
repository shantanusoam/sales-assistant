"""Org-scoped generic outgoing webhook endpoints — the "plugin" half of post-call
distribution. Delivery itself (HMAC-signed POST after a consented call ends) lives
in main.py's push_summary_to_webhooks, alongside the WhatsApp/CRM push points."""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import WebhookNode


class CreateWebhookRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2000)


class UpdateWebhookRequest(BaseModel):
    enabled: bool


def _public(node: WebhookNode) -> dict:
    return {
        "id": node.id,
        "url": node.url,
        "enabled": node.enabled,
        "secret": node.secret,  # shown once-ish, needed so the admin can verify signatures on their receiving end
        "created_at": node.created_at.isoformat(),
    }


def build_webhook_router(get_db, require_auth) -> APIRouter:
    router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

    def require_admin(claims: dict) -> None:
        if claims["role"] != "admin":
            raise HTTPException(403, "Only an org admin can manage webhook nodes.")

    @router.get("")
    async def list_webhooks(claims: dict = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> dict:
        nodes = await db.scalars(select(WebhookNode).where(WebhookNode.organization_id == claims["org_id"]))
        return {"webhooks": [_public(n) for n in nodes]}

    @router.post("")
    async def create_webhook(payload: CreateWebhookRequest, claims: dict = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> dict:
        require_admin(claims)
        if not (payload.url.startswith("https://") or payload.url.startswith("http://")):
            raise HTTPException(400, "Webhook URL must start with http:// or https://.")
        node = WebhookNode(organization_id=claims["org_id"], url=payload.url, secret=secrets.token_hex(24))
        db.add(node)
        await db.commit()
        return _public(node)

    @router.patch("/{webhook_id}")
    async def update_webhook(webhook_id: str, payload: UpdateWebhookRequest, claims: dict = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> dict:
        require_admin(claims)
        node = await db.get(WebhookNode, webhook_id)
        if node is None or node.organization_id != claims["org_id"]:
            raise HTTPException(404, "Webhook not found.")
        node.enabled = payload.enabled
        await db.commit()
        return _public(node)

    @router.delete("/{webhook_id}")
    async def delete_webhook(webhook_id: str, claims: dict = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> dict:
        require_admin(claims)
        node = await db.get(WebhookNode, webhook_id)
        if node is None or node.organization_id != claims["org_id"]:
            raise HTTPException(404, "Webhook not found.")
        await db.delete(node)
        await db.commit()
        return {"deleted": True}

    @router.post("/{webhook_id}/test")
    async def test_webhook(webhook_id: str, claims: dict = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> dict:
        require_admin(claims)
        node = await db.get(WebhookNode, webhook_id)
        if node is None or node.organization_id != claims["org_id"]:
            raise HTTPException(404, "Webhook not found.")
        payload = {
            "event": "webhook.test",
            "webhook_id": node.id,
            "organization_id": node.organization_id,
            "disposition": "interested",
            "coaching_score": 88,
            "summary": "Test webhook delivery from Sales Copilot Settings.",
        }
        body = json.dumps(payload, sort_keys=True).encode()
        signature = hmac.new(node.secret.encode(), body, hashlib.sha256).hexdigest()
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.post(
                    node.url,
                    content=body,
                    headers={"Content-Type": "application/json", "X-Signature-SHA256": signature},
                )
        except Exception as exc:
            raise HTTPException(502, f"Webhook test delivery failed: {exc}") from exc
        if resp.status_code >= 400:
            raise HTTPException(502, f"Endpoint returned HTTP {resp.status_code}.")
        return {"ok": True, "status_code": resp.status_code}

    return router

"""Org-scoped call history endpoints, reading the Call/Turn/Hint rows written by main.py."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .models import Call


def _call_summary(call: Call) -> dict:
    return {
        "id": call.id,
        "channel": call.channel,
        "rep_user_id": call.rep_user_id,
        "to_number": call.to_number,
        "from_number": call.from_number,
        "started_at": call.started_at.isoformat(),
        "ended_at": call.ended_at.isoformat() if call.ended_at else None,
        "turn_count": len(call.turns),
        "hint_count": len(call.hints),
    }


def build_calls_router(get_db, require_auth) -> APIRouter:
    router = APIRouter(prefix="/api/calls", tags=["calls"])

    @router.get("")
    async def list_calls(claims: dict = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> dict:
        calls = await db.scalars(
            select(Call)
            .where(Call.organization_id == claims["org_id"])
            .options(selectinload(Call.turns), selectinload(Call.hints))
            .order_by(Call.started_at.desc())
            .limit(100)
        )
        return {"calls": [_call_summary(c) for c in calls]}

    @router.get("/{call_id}")
    async def get_call(call_id: str, claims: dict = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> dict:
        call = await db.get(Call, call_id, options=[selectinload(Call.turns), selectinload(Call.hints)])
        if call is None or call.organization_id != claims["org_id"]:
            raise HTTPException(404, "Call not found.")
        return {
            **_call_summary(call),
            "turns": [
                {"source": t.source, "text": t.text, "seq": t.seq, "created_at": t.created_at.isoformat()}
                for t in call.turns
            ],
            "hints": [
                {
                    "text": h.text,
                    "method": h.method,
                    "sources": json.loads(h.sources_json),
                    "processing_ms": h.processing_ms,
                    "created_at": h.created_at.isoformat(),
                }
                for h in call.hints
            ],
        }

    return router

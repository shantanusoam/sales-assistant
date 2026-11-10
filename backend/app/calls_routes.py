"""Org-scoped call history, coaching analytics, and on-demand summary endpoints."""
from __future__ import annotations

from collections import Counter
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .config import Settings
from .models import Call, CallSummary, User
from .post_call import TurnLike, generate_call_summary


def _call_summary(call: Call, rep_names: dict[str, str] | None = None) -> dict:
    objection_count = sum(1 for t in call.turns if "objection" in json.loads(t.intents_json or "[]"))
    negative_count = sum(1 for t in call.turns if t.sentiment == "negative")
    return {
        "id": call.id,
        "channel": call.channel,
        "rep_user_id": call.rep_user_id,
        "rep_name": (rep_names or {}).get(call.rep_user_id or "", None),
        "to_number": call.to_number,
        "from_number": call.from_number,
        "started_at": call.started_at.isoformat(),
        "ended_at": call.ended_at.isoformat() if call.ended_at else None,
        "turn_count": len(call.turns),
        "hint_count": len(call.hints),
        "objection_count": objection_count,
        "negative_count": negative_count,
        "coaching_score": call.summary.coaching_score if call.summary else None,
        "disposition": call.summary.disposition if call.summary else None,
        "summary_preview": call.summary.summary[:160] if call.summary and call.summary.summary else None,
        "consent_confirmed": call.consent_confirmed_at is not None,
    }


def build_calls_router(get_db, require_auth, settings: Settings | None = None) -> APIRouter:
    router = APIRouter(prefix="/api/calls", tags=["calls"])
    config = settings or Settings()

    async def _rep_names_for_calls(db: AsyncSession, calls: list[Call]) -> dict[str, str]:
        rep_ids = {c.rep_user_id for c in calls if c.rep_user_id}
        if not rep_ids:
            return {}
        users = await db.scalars(select(User).where(User.id.in_(rep_ids)))
        return {u.id: u.name for u in users}

    @router.get("/analytics")
    async def call_analytics(claims: dict = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> dict:
        calls = list(
            await db.scalars(
                select(Call)
                .where(Call.organization_id == claims["org_id"])
                .options(selectinload(Call.turns), selectinload(Call.hints), selectinload(Call.summary))
                .order_by(Call.started_at.desc())
                .limit(200)
            )
        )
        rep_names = await _rep_names_for_calls(db, calls)
        scores = [c.summary.coaching_score for c in calls if c.summary and c.summary.coaching_score is not None]
        dispositions = Counter(c.summary.disposition for c in calls if c.summary and c.summary.disposition)
        channels = Counter(c.channel for c in calls)
        total_turns = sum(len(c.turns) for c in calls)
        total_hints = sum(len(c.hints) for c in calls)
        total_objections = sum(
            1 for c in calls for t in c.turns if "objection" in json.loads(t.intents_json or "[]")
        )
        rep_buckets: dict[str, list[int]] = {}
        rep_counts: Counter = Counter()
        for c in calls:
            uid = c.rep_user_id or "unassigned"
            rep_counts[uid] += 1
            if c.summary and c.summary.coaching_score is not None:
                rep_buckets.setdefault(uid, []).append(c.summary.coaching_score)
        reps = [
            {
                "user_id": uid,
                "name": rep_names.get(uid, "Rep"),
                "call_count": count,
                "avg_score": round(sum(rep_buckets[uid]) / len(rep_buckets[uid])) if uid in rep_buckets else None,
            }
            for uid, count in rep_counts.most_common()
        ]
        return {
            "total_calls": len(calls),
            "completed_calls": sum(1 for c in calls if c.ended_at is not None),
            "consented_calls": sum(1 for c in calls if c.consent_confirmed_at is not None),
            "avg_coaching_score": round(sum(scores) / len(scores)) if scores else None,
            "total_turns": total_turns,
            "total_hints": total_hints,
            "total_objections": total_objections,
            "dispositions": dict(dispositions),
            "channels": dict(channels),
            "reps": reps,
        }

    @router.get("")
    async def list_calls(
        disposition: str | None = Query(default=None),
        channel: str | None = Query(default=None),
        q: str | None = Query(default=None),
        claims: dict = Depends(require_auth),
        db: AsyncSession = Depends(get_db),
    ) -> dict:
        calls = list(
            await db.scalars(
                select(Call)
                .where(Call.organization_id == claims["org_id"])
                .options(selectinload(Call.turns), selectinload(Call.hints), selectinload(Call.summary))
                .order_by(Call.started_at.desc())
                .limit(100)
            )
        )
        if channel:
            calls = [c for c in calls if c.channel == channel]
        if disposition:
            calls = [c for c in calls if c.summary and c.summary.disposition == disposition]
        if q and q.strip():
            needle = q.strip().casefold()
            calls = [
                c for c in calls
                if (c.summary and needle in (c.summary.summary or "").casefold())
                or any(needle in (t.text or "").casefold() for t in c.turns)
                or any(needle in (h.text or "").casefold() for h in c.hints)
                or (c.to_number and needle in c.to_number.casefold())
            ]
        rep_names = await _rep_names_for_calls(db, calls)
        return {"calls": [_call_summary(c, rep_names) for c in calls]}

    @router.get("/{call_id}")
    async def get_call(call_id: str, claims: dict = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> dict:
        call = await db.get(Call, call_id, options=[selectinload(Call.turns), selectinload(Call.hints), selectinload(Call.summary)])
        if call is None or call.organization_id != claims["org_id"]:
            raise HTTPException(404, "Call not found.")
        rep_names = await _rep_names_for_calls(db, [call])
        return {
            **_call_summary(call, rep_names),
            "summary": {
                "text": call.summary.summary,
                "coaching_score": call.summary.coaching_score,
                "coaching_notes": call.summary.coaching_notes,
                "follow_up_email": call.summary.follow_up_email,
                "disposition": call.summary.disposition,
                "method": call.summary.method,
            } if call.summary else None,
            "turns": [
                {
                    "source": t.source, "text": t.text, "seq": t.seq,
                    "sentiment": t.sentiment, "intents": json.loads(t.intents_json or "[]"),
                    "created_at": t.created_at.isoformat(),
                }
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

    @router.post("/{call_id}/summarize")
    async def regenerate_summary(call_id: str, claims: dict = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> dict:
        call = await db.get(Call, call_id, options=[selectinload(Call.turns), selectinload(Call.summary)])
        if call is None or call.organization_id != claims["org_id"]:
            raise HTTPException(404, "Call not found.")
        turns = [TurnLike(t.source, t.text) for t in call.turns]
        data = await generate_call_summary(turns, config)
        if call.summary:
            call.summary.summary = data["summary"]
            call.summary.coaching_score = data["coaching_score"]
            call.summary.coaching_notes = data["coaching_notes"]
            call.summary.follow_up_email = data["follow_up_email"]
            call.summary.disposition = data["disposition"]
            call.summary.method = data["method"]
        else:
            db.add(CallSummary(
                call_id=call.id,
                summary=data["summary"],
                coaching_score=data["coaching_score"],
                coaching_notes=data["coaching_notes"],
                follow_up_email=data["follow_up_email"],
                disposition=data["disposition"],
                method=data["method"],
            ))
        await db.commit()
        return {
            "text": data["summary"],
            "coaching_score": data["coaching_score"],
            "coaching_notes": data["coaching_notes"],
            "follow_up_email": data["follow_up_email"],
            "disposition": data["disposition"],
            "method": data["method"],
        }

    return router

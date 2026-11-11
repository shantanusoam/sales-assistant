"""Data lifecycle helpers: retention pruning and org-scoped deletion.

Pure async functions so they're directly testable and callable from the background
worker's periodic tick as well as from request handlers.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Call, CallSummary, Hint, Turn


async def delete_call_rows(db: AsyncSession, call_id: str) -> bool:
    """Delete one call and all child rows (summary, hints, turns) in FK-safe order.
    Returns False when the call does not exist."""
    call = await db.get(Call, call_id)
    if call is None:
        return False
    await db.execute(delete(CallSummary).where(CallSummary.call_id == call_id))
    await db.execute(delete(Hint).where(Hint.call_id == call_id))
    await db.execute(delete(Turn).where(Turn.call_id == call_id))
    await db.delete(call)
    await db.commit()
    return True


async def prune_old_calls(db: AsyncSession, retention_days: int) -> int:
    """Delete calls whose started_at is older than retention_days. 0 disables."""
    if retention_days <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    # SQLite stores naive datetimes; compare in naive UTC.
    cutoff = cutoff.replace(tzinfo=None)
    old_ids = list(await db.scalars(select(Call.id).where(Call.started_at < cutoff)))
    for call_id in old_ids:
        await delete_call_rows(db, call_id)
    return len(old_ids)

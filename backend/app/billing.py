"""Plans, monthly call metering, and quota enforcement.

The MVP billing model is deliberately simple: each organization sits on a plan whose
monthly_call_limit caps new calls (browser, Twilio, and mobile logger alike) within
the current UTC month. Plan changes are admin-manual for now; the Razorpay order +
webhook flow slots into billing_routes.py without touching callers.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Call, Organization

PLAN_ORDER = ("pilot", "growth", "scale")

PLANS: dict[str, dict] = {
    "pilot": {"label": "Pilot", "monthly_calls": 50, "price_note": "Free while piloting"},
    "growth": {"label": "Growth", "monthly_calls": 500, "price_note": "Per-seat pricing on checkout"},
    "scale": {"label": "Scale", "monthly_calls": None, "price_note": "Volume pricing, talk to us"},
}

DEFAULT_PLAN = "pilot"


def plan_limit(plan: str, override: int | None) -> int | None:
    """Effective monthly call limit: explicit per-org override wins over the plan."""
    if override is not None:
        return max(0, int(override))
    return PLANS.get(plan, PLANS[DEFAULT_PLAN])["monthly_calls"]


def month_start_utc() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def usage_for_org(db: AsyncSession, organization_id: str) -> dict:
    """Returns {plan, monthly_call_limit, calls_used_this_month, calls_remaining}."""
    org = await db.get(Organization, organization_id)
    if org is None:
        return {
            "plan": DEFAULT_PLAN,
            "monthly_call_limit": PLANS[DEFAULT_PLAN]["monthly_calls"],
            "calls_used_this_month": 0,
            "calls_remaining": PLANS[DEFAULT_PLAN]["monthly_calls"],
        }
    limit = plan_limit(org.plan, org.monthly_call_limit_override)
    used = int(await db.scalar(
        select(func.count(Call.id)).where(
            Call.organization_id == organization_id,
            Call.started_at >= month_start_utc(),
        )
    ) or 0)
    remaining = None if limit is None else max(0, limit - used)
    return {
        "plan": org.plan,
        "monthly_call_limit": limit,
        "calls_used_this_month": used,
        "calls_remaining": remaining,
    }


async def calls_allowed(db: AsyncSession, organization_id: str) -> bool:
    usage = await usage_for_org(db, organization_id)
    limit = usage["monthly_call_limit"]
    return limit is None or usage["calls_used_this_month"] < limit


QUOTA_MESSAGE = (
    "Your organization reached its monthly call limit. "
    "Ask an admin to upgrade in Settings → Billing."
)

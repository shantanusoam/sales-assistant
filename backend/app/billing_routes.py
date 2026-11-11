"""Billing endpoints: usage/plan status and admin plan switching.

Plan changes are manual/admin-driven until the Razorpay order + webhook flow lands
(the provider keys and a PaymentProvider seam are already provisioned in config);
nothing here assumes a gateway, so wiring one later touches only this file.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from .billing import PLAN_ORDER, PLANS, usage_for_org
from .models import Organization


class ChangePlanRequest(BaseModel):
    plan: str


def build_billing_router(get_db, require_auth) -> APIRouter:
    router = APIRouter(prefix="/api/billing", tags=["billing"])

    @router.get("/status")
    async def status(claims: dict = Depends(require_auth), db: AsyncSession = Depends(get_db)) -> dict:
        usage = await usage_for_org(db, claims["org_id"])
        return {**usage, "plans": PLANS}

    @router.post("/plan")
    async def change_plan(
        payload: ChangePlanRequest, claims: dict = Depends(require_auth), db: AsyncSession = Depends(get_db)
    ) -> dict:
        if claims["role"] != "admin":
            raise HTTPException(403, "Only an org admin can change the billing plan.")
        if payload.plan not in PLANS:
            raise HTTPException(400, f"Unknown plan. Supported: {', '.join(PLAN_ORDER)}.")
        org = await db.get(Organization, claims["org_id"])
        if org is None:
            raise HTTPException(404, "Organization not found.")
        org.plan = payload.plan
        await db.commit()
        usage = await usage_for_org(db, claims["org_id"])
        return {"ok": True, **usage}

    return router

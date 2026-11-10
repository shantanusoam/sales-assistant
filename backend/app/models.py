"""SQLAlchemy ORM models. Schema changes go through an Alembic migration (alembic/versions/)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    memberships: Mapped[list["Membership"]] = relationship(back_populates="organization")


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    name: Mapped[str] = mapped_column(String(200))
    whatsapp_number: Mapped[str | None] = mapped_column(String(32), nullable=True)  # E.164, e.g. +9198...
    whatsapp_recap_enabled: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    memberships: Mapped[list["Membership"]] = relationship(back_populates="user")


class Membership(Base):
    """A user's role within one organization. A user may belong to more than one org."""

    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "organization_id", name="uq_membership_user_org"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    role: Mapped[str] = mapped_column(String(20))  # "admin" | "manager" | "rep"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    user: Mapped[User] = relationship(back_populates="memberships")
    organization: Mapped[Organization] = relationship(back_populates="memberships")


class Call(Base):
    """One live session: a browser-mic test session or a Twilio phone call."""

    __tablename__ = "calls"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    organization_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id"), index=True, nullable=True)
    rep_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    channel: Mapped[str] = mapped_column(String(20))  # "browser" | "twilio"
    twilio_call_sid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    to_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    from_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consent_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    turns: Mapped[list["Turn"]] = relationship(back_populates="call", order_by="Turn.seq")
    hints: Mapped[list["Hint"]] = relationship(back_populates="call", order_by="Hint.created_at")
    summary: Mapped["CallSummary | None"] = relationship(back_populates="call")


class Turn(Base):
    """One finalized utterance (from either side of the conversation)."""

    __tablename__ = "turns"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    call_id: Mapped[str] = mapped_column(ForeignKey("calls.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(32))  # microphone | manual-test | twilio-customer | twilio-rep
    text: Mapped[str] = mapped_column(Text)
    sentiment: Mapped[str] = mapped_column(String(20), default="neutral")  # positive | neutral | negative
    intents_json: Mapped[str] = mapped_column(Text, default="[]")  # e.g. ["objection", "pricing"]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    call: Mapped[Call] = relationship(back_populates="turns")


class Hint(Base):
    """One generated coaching suggestion."""

    __tablename__ = "hints"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    call_id: Mapped[str] = mapped_column(ForeignKey("calls.id"), index=True)
    text: Mapped[str] = mapped_column(Text)
    method: Mapped[str] = mapped_column(String(20))  # "ai" | "rules-demo"
    sources_json: Mapped[str] = mapped_column(Text, default="[]")
    processing_ms: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    call: Mapped[Call] = relationship(back_populates="hints")


class CallSummary(Base):
    """One post-call analysis: summary, coaching score, and a drafted follow-up email."""

    __tablename__ = "call_summaries"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    call_id: Mapped[str] = mapped_column(ForeignKey("calls.id"), unique=True, index=True)
    summary: Mapped[str] = mapped_column(Text)
    coaching_score: Mapped[int] = mapped_column(Integer)
    coaching_notes: Mapped[str] = mapped_column(Text)
    follow_up_email: Mapped[str] = mapped_column(Text)
    disposition: Mapped[str] = mapped_column(String(20), default="no_decision")
    method: Mapped[str] = mapped_column(String(20))  # "ai" | "rules-demo"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    call: Mapped[Call] = relationship(back_populates="summary")


class CRMConnection(Base):
    """One organization's connection to a third-party CRM."""

    __tablename__ = "crm_connections"
    __table_args__ = (UniqueConstraint("organization_id", name="uq_crm_connection_org"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    provider: Mapped[str] = mapped_column(String(40))  # e.g. "hubspot"
    encrypted_token: Mapped[str] = mapped_column(Text)
    auto_push: Mapped[bool] = mapped_column(default=True)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class WebhookNode(Base):
    """A generic outgoing webhook an org admin wires up to receive post-call summaries
    (Slack, Zapier, n8n, a spreadsheet, anything) — the generic half of the "plugin"
    distribution system, alongside the built-in WhatsApp recap."""

    __tablename__ = "webhook_nodes"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    url: Mapped[str] = mapped_column(String(2000))
    secret: Mapped[str] = mapped_column(String(100))  # HMAC-SHA256 signs each delivered payload
    enabled: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

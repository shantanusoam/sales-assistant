"""Transactional email (invites, password resets).

Uses SMTP when configured. Without SMTP_HOST the message is written to the server
log instead — local/demo mode stays fully functional without any outbound email
infrastructure, and callers get `False` back so they can surface the link in-app
when delivery did not really happen.
"""
from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage

from .config import Settings

logger = logging.getLogger(__name__)


def _send_smtp(settings: Settings, to: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = settings.email_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    if settings.smtp_port == 465:
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
            smtp.ehlo()
            if settings.smtp_port == 587:
                smtp.starttls()
                smtp.ehlo()
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(msg)


def build_mailer(settings: Settings):
    """Returns async send_email(to, subject, body) -> bool (True = actually sent)."""

    async def send_email(to: str, subject: str, body: str) -> bool:
        if not settings.smtp_host:
            logger.info(
                "EMAIL (dev mode, SMTP_HOST not configured) to=%s subject=%s\n%s", to, subject, body
            )
            return False
        try:
            await asyncio.to_thread(_send_smtp, settings, to, subject, body)
            return True
        except Exception:
            logger.exception("Email delivery to %s failed", to)
            return False

    return send_email

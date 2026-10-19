"""Outgoing email for the Daily Brief, via the standard library's smtplib (run in a worker thread)."""

from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage

from app.core.config import Settings

logger = logging.getLogger(__name__)


def email_configured(settings: Settings) -> bool:
    return bool(settings.smtp_host and settings.smtp_from)


def _send(settings: Settings, to: str, subject: str, body: str) -> None:
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
        smtp.starttls()
        if settings.smtp_user and settings.smtp_password:
            smtp.login(settings.smtp_user, settings.smtp_password.get_secret_value())
        smtp.send_message(message)


async def send_email(settings: Settings, to: str, subject: str, body: str) -> bool:
    """Returns True on success. Failures are logged (without credentials) and never raise."""
    if not email_configured(settings):
        return False
    try:
        await asyncio.to_thread(_send, settings, to, subject, body)
    except (OSError, smtplib.SMTPException) as exc:
        logger.warning("Brief email to user failed: %s", type(exc).__name__)
        return False
    return True

"""Outgoing email for the Daily Brief, via the standard library's smtplib (run in a worker thread).

Every email carries an unsubscribe link (in the body and as List-Unsubscribe headers for one-click
unsubscribe in mail clients) and the sender's physical postal address. If either can't be produced, because
PUBLIC_APP_URL or MAIL_POSTAL_ADDRESS isn't set, email counts as not configured and nothing is sent.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage

from app.core.config import Settings

logger = logging.getLogger(__name__)


def email_configured(settings: Settings) -> bool:
    return bool(
        settings.smtp_host.strip()
        and settings.smtp_from.strip()
        and settings.public_app_url.strip()
        and settings.mail_postal_address.strip()
    )


def unsubscribe_url(settings: Settings, token: str) -> str:
    return f"{settings.public_app_url.strip().rstrip('/')}/api/v1/email/unsubscribe?token={token}"


def footer(settings: Settings, unsubscribe_link: str) -> str:
    return (
        "\n\n--\n"
        "You're receiving this because you turned on Daily Brief emails in MarketPulse.\n"
        f"Unsubscribe: {unsubscribe_link}\n"
        f"MarketPulse, {settings.mail_postal_address.strip()}\n"
    )


def build_message(
    settings: Settings, to: str, subject: str, body: str, unsubscribe_link: str
) -> EmailMessage:
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = to
    message["Subject"] = subject
    # RFC 8058 one-click unsubscribe: mail clients POST to the link without the user opening the email.
    message["List-Unsubscribe"] = f"<{unsubscribe_link}>"
    message["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    message.set_content(body.rstrip() + footer(settings, unsubscribe_link))
    return message


def _send(settings: Settings, message: EmailMessage) -> None:
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
        smtp.starttls()
        if settings.smtp_user and settings.smtp_password:
            smtp.login(settings.smtp_user, settings.smtp_password.get_secret_value())
        smtp.send_message(message)


async def send_email(settings: Settings, to: str, subject: str, body: str, unsubscribe_link: str) -> bool:
    """Returns True on success. Failures are logged (without credentials) and never raise."""
    if not email_configured(settings):
        return False
    try:
        await asyncio.to_thread(_send, settings, build_message(settings, to, subject, body, unsubscribe_link))
    except (OSError, smtplib.SMTPException) as exc:
        logger.warning("Brief email to user failed: %s", type(exc).__name__)
        return False
    return True

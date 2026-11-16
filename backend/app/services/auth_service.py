"""Registration, login, and refresh-token sessions."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import CacheBackend
from app.core.config import Settings
from app.core.errors import AgeRestricted, Conflict, TooManyRequests, Unauthorized, ValidationFailed
from app.core.security import (
    TokenSigner,
    hash_password,
    hash_refresh_token,
    needs_rehash,
    new_refresh_token,
    verify_password,
)
from app.models import Portfolio, RefreshToken, User, Watchlist

logger = logging.getLogger(__name__)

# Deliberately simple: one "@", no spaces, a dot in the domain. Real validation is the user receiving email.
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128
DEFAULT_WATCHLIST_NAME = "My watchlist"
DEFAULT_PORTFOLIO_NAME = "Paper portfolio"


@dataclass(frozen=True)
class IssuedSession:
    user: User
    access_token: str
    access_expires_at: datetime
    refresh_token: str
    refresh_expires_at: datetime


def normalize_email(email: str) -> str:
    return email.strip().lower()


def validate_registration(email: str, password: str, timezone: str) -> None:
    if not _EMAIL.match(email) or len(email) > 254:
        raise ValidationFailed("Please enter a valid email address.", code="invalid_email")
    if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
        raise ValidationFailed(
            f"Passwords must be {MIN_PASSWORD_LENGTH}-{MAX_PASSWORD_LENGTH} characters.",
            code="invalid_password",
        )
    validate_timezone(timezone)


MAX_PLAUSIBLE_AGE = 120


def age_on(birth_date: date, today: date) -> int:
    """Completed years between `birth_date` and `today`."""
    before_birthday = (today.month, today.day) < (birth_date.month, birth_date.day)
    return today.year - birth_date.year - (1 if before_birthday else 0)


def validate_age(birth_date: date | None, minimum_age: int, today: date | None = None) -> None:
    """Refuse signups below `minimum_age`. The date is only checked here; nothing stores it."""
    today = today or datetime.now(UTC).date()
    if birth_date is None:
        raise ValidationFailed("Please enter your date of birth.", code="birth_date_required")
    if birth_date > today or age_on(birth_date, today) > MAX_PLAUSIBLE_AGE:
        raise ValidationFailed("Please enter a valid date of birth.", code="invalid_birth_date")
    if age_on(birth_date, today) < minimum_age:
        raise AgeRestricted(f"You must be at least {minimum_age} years old to create an account.")


def validate_timezone(timezone: str) -> None:
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValidationFailed("Unknown timezone.", code="invalid_timezone") from exc


async def register(
    session: AsyncSession,
    settings: Settings,
    email: str,
    password: str,
    display_name: str | None,
    timezone: str,
    birth_date: date | None,
) -> User:
    email = normalize_email(email)
    validate_registration(email, password, timezone)
    validate_age(birth_date, settings.min_signup_age)
    user = User(
        email=email,
        password_hash=hash_password(password),
        display_name=(display_name or "").strip() or email.split("@")[0],
        timezone=timezone,
        base_currency=settings.paper_base_currency,
    )
    session.add(user)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise Conflict("An account with this email already exists.", code="email_taken") from exc
    # Every account starts with an empty watchlist and a funded paper portfolio.
    session.add(Watchlist(user_id=user.id, name=DEFAULT_WATCHLIST_NAME))
    session.add(
        Portfolio(
            user_id=user.id,
            name=DEFAULT_PORTFOLIO_NAME,
            base_currency=settings.paper_base_currency,
            starting_cash=settings.paper_starting_cash,
            cash=settings.paper_starting_cash,
        )
    )
    await session.flush()
    logger.info("Registered user %s", user.id)
    return user


async def authenticate(
    session: AsyncSession, cache: CacheBackend, settings: Settings, email: str, password: str, client: str
) -> User:
    email = normalize_email(email)
    lock_key = f"mp:login-failures:{email}:{client}"
    failures = int(await cache.get(lock_key) or 0)
    if failures >= settings.login_max_failures:
        raise TooManyRequests("Too many failed sign-in attempts. Please wait a few minutes and try again.")

    user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if not verify_password(password, user.password_hash if user else None) or user is None:
        await cache.set(lock_key, str(failures + 1), settings.login_lockout_s)
        raise Unauthorized("Incorrect email or password.", code="invalid_credentials")

    await cache.delete(lock_key)
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    return user


async def issue_session(
    session: AsyncSession, signer: TokenSigner, settings: Settings, user: User, now: datetime | None = None
) -> IssuedSession:
    now = now or datetime.now(UTC)
    access_token, access_expires = signer.create_access_token(user.id, now)
    refresh_token = new_refresh_token()
    refresh_expires = now + timedelta(days=settings.refresh_token_ttl_days)
    session.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_refresh_token(refresh_token),
            created_at=now,
            expires_at=refresh_expires,
        )
    )
    await session.flush()
    return IssuedSession(user, access_token, access_expires, refresh_token, refresh_expires)


async def rotate_session(
    session: AsyncSession,
    signer: TokenSigner,
    settings: Settings,
    refresh_token: str,
    now: datetime | None = None,
) -> IssuedSession:
    """Exchange a refresh token for a new session. Presenting an already-used token revokes every session."""
    now = now or datetime.now(UTC)
    stored = (
        await session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(refresh_token))
        )
    ).scalar_one_or_none()
    if stored is None:
        raise Unauthorized("Your session has ended. Please sign in again.", code="invalid_refresh")
    if stored.revoked_at is not None:
        if now - _aware(stored.revoked_at) <= timedelta(seconds=settings.refresh_reuse_grace_s):
            # Two tabs refreshed at once and the other one won; its new cookie is already in the browser.
            raise Unauthorized("Your session was just refreshed. Please retry.", code="refresh_race")
        # A rotated token came back long after rotation: it was probably stolen. End all sessions.
        logger.warning("Refresh token reuse detected for user %s; revoking all sessions", stored.user_id)
        await revoke_all(session, stored.user_id, now)
        await session.commit()
        raise Unauthorized("Your session has ended. Please sign in again.", code="invalid_refresh")
    if _aware(stored.expires_at) <= now:
        raise Unauthorized("Your session has expired. Please sign in again.", code="invalid_refresh")

    stored.revoked_at = now
    user = await session.get(User, stored.user_id)
    if user is None:
        raise Unauthorized("Your session has ended. Please sign in again.", code="invalid_refresh")
    return await issue_session(session, signer, settings, user, now)


async def revoke(session: AsyncSession, refresh_token: str, now: datetime | None = None) -> None:
    await session.execute(
        update(RefreshToken)
        .where(
            RefreshToken.token_hash == hash_refresh_token(refresh_token), RefreshToken.revoked_at.is_(None)
        )
        .values(revoked_at=now or datetime.now(UTC))
    )


async def revoke_all(session: AsyncSession, user_id: int, now: datetime | None = None) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now or datetime.now(UTC))
    )


def _aware(value: datetime) -> datetime:
    # SQLite drops tzinfo on read; every timestamp we store is UTC.
    return value if value.tzinfo else value.replace(tzinfo=UTC)

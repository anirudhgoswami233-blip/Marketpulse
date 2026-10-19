"""Daily Brief job: runs every few minutes, builds briefs for users whose local brief time has passed.

All due users' symbols are gathered first and each signal is computed once, sequentially and at background
priority, so the limiter spreads the calls out. A brief run never bursts the provider budgets.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime

from app.container import Container
from app.core.errors import AppError, ProviderError
from app.core.ratelimit import background_priority
from app.models import SignalRecord, User
from app.services import brief_service, markets_service, signal_service
from app.services.brief_service import BriefSymbol, TemplateWriter
from app.services.email_service import email_configured, send_email

logger = logging.getLogger(__name__)


async def compute_signals(
    container: Container, symbols: Sequence[BriefSymbol], now: datetime
) -> dict[int, SignalRecord]:
    signals: dict[int, SignalRecord] = {}
    unique = {s.symbol.id: s.symbol for s in symbols}
    with background_priority():
        for symbol in unique.values():
            # One session per symbol: a failure (and its rollback) can't expire objects we still use.
            async with container.session_factory() as session:
                try:
                    signals[symbol.id] = await signal_service.get_or_compute(
                        session,
                        container.providers.history,
                        container.providers.news,
                        container.cache,
                        symbol,
                        now,
                    )
                except (AppError, ProviderError) as exc:
                    logger.warning("Brief: no signal for %s: %s", symbol.symbol, exc)
    return signals


async def ensure_market_context(container: Container) -> None:
    """Briefs describe the last session through the overview snapshot (regional ETFs, movers). Right after a
    restart it may be empty, so fetch just the missing quotes first, at background priority."""
    snapshot = await markets_service.load_snapshot(container.cache)
    missing = markets_service.missing_brief_symbols(snapshot)
    if not missing:
        return
    logger.info("Brief: fetching %d missing market-snapshot quotes first", len(missing))
    await markets_service.refresh_snapshot(container.providers.quotes, container.cache, {}, symbols=missing)


async def generate_for(container: Container, users: Sequence[User], now: datetime | None = None) -> int:
    """Build briefs for `users`. Returns how many were built."""
    now = now or datetime.now(UTC)
    writer = TemplateWriter()
    built = 0
    await ensure_market_context(container)
    async with container.session_factory() as session:
        per_user = {u.id: await brief_service.brief_symbols(session, container.cache, u) for u in users}
        all_symbols = [s for entries in per_user.values() for s in entries]
        signals = await compute_signals(container, all_symbols, now)
        for user in users:
            try:
                brief = await brief_service.build_brief(
                    session, container.cache, writer, user, per_user[user.id], signals, now
                )
            except Exception:
                await session.rollback()
                logger.exception("Brief generation failed for user %s", user.id)
                continue
            built += 1
            if user.brief_email_enabled and email_configured(container.settings):
                sent = await send_email(
                    container.settings,
                    user.email,
                    f"Your MarketPulse brief for {brief.brief_date:%d %b %Y}",
                    brief.summary_md,
                )
                if sent:
                    brief.emailed_at = datetime.now(UTC)
                    await session.commit()
    return built


async def run(container: Container) -> None:
    now = datetime.now(UTC)
    async with container.session_factory() as session:
        users = await brief_service.due_users(session, now)
    if not users:
        return
    started = datetime.now(UTC)
    built = await generate_for(container, users, now)
    logger.info(
        "Daily brief run: %d/%d briefs in %.0fs",
        built,
        len(users),
        (datetime.now(UTC) - started).total_seconds(),
    )

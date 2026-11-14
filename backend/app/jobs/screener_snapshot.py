"""Keeps the screener's universe ready: fundamentals about once a day, and a technical signal per symbol
for the last completed session. Everything runs at background priority, so the limiter spreads it out.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select

from app.container import Container
from app.core.errors import ProviderError
from app.core.ratelimit import background_priority
from app.models import Symbol
from app.services import screener_service, signal_service
from app.services.signal_service import SignalsUnavailable

logger = logging.getLogger(__name__)

# Stop the signals pass after this many failures in a row (e.g. the history provider is rate-limited), so a
# bad hour doesn't burn the daily budget; the next run picks up where this one stopped.
MAX_CONSECUTIVE_SIGNAL_FAILURES = 3


async def run(container: Container) -> None:
    now = datetime.now(UTC)
    snapshot = await screener_service.load_fundamentals(container.cache)
    if screener_service.needs_refresh(snapshot, now):
        refreshed = await screener_service.refresh_fundamentals(
            container.providers.reference, container.cache
        )
        logger.info("Screener fundamentals refreshed: %d symbols", len(refreshed.rows))
    await refresh_signals(container, now)


async def refresh_signals(container: Container, now: datetime) -> int:
    """Make sure each universe symbol has a signal for the last completed session. Symbols that already
    have one cost a single DB read. Returns how many symbols now have a current signal."""
    ready = failures = 0
    with background_priority():
        for ticker in screener_service.universe():
            # One session per symbol: a failure can't expire ORM objects another symbol still needs.
            async with container.session_factory() as session:
                symbol = (
                    await session.scalars(
                        select(Symbol).where(
                            Symbol.symbol == ticker,
                            Symbol.exchange_code == screener_service.UNIVERSE_EXCHANGE,
                        )
                    )
                ).first()
                if symbol is None:
                    continue
                try:
                    await signal_service.get_or_compute(
                        session,
                        container.providers.history,
                        container.providers.news,
                        container.cache,
                        symbol,
                        now,
                    )
                except (SignalsUnavailable, ProviderError) as exc:
                    failures += 1
                    logger.info("Screener: no signal for %s: %s", ticker, exc)
                    if failures >= MAX_CONSECUTIVE_SIGNAL_FAILURES:
                        logger.warning(
                            "Screener: stopping the signals pass after %d failures in a row", failures
                        )
                        break
                else:
                    failures = 0
                    ready += 1
    return ready

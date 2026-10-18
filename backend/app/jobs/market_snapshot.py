"""Keeps the markets-overview snapshot fresh without bursting the Finnhub budget."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.container import Container
from app.models import Symbol
from app.services import markets_service
from app.services.reference_data import overview_config

logger = logging.getLogger(__name__)


async def run(container: Container) -> None:
    settings = container.settings
    provider = container.providers.quotes
    now = datetime.now(UTC)
    closed_interval = timedelta(seconds=settings.overview_refresh_closed_s)
    if not await markets_service.should_refresh(
        container.providers.market_status, container.cache, now, closed_interval
    ):
        logger.debug("Overview snapshot is current; skipping refresh")
        return

    symbols = overview_config().all_symbols()
    async with container.session_factory() as session:
        rows = await session.execute(
            select(Symbol.symbol, Symbol.currency).where(
                Symbol.symbol.in_(symbols), Symbol.exchange_code == "US"
            )
        )
        currencies: dict[str, str | None] = {symbol: currency for symbol, currency in rows.all()}

    started = datetime.now(UTC)
    snapshot = await markets_service.refresh_snapshot(provider, container.cache, currencies)
    logger.info(
        "Overview snapshot refreshed: %d/%d quotes in %.0fs",
        len(snapshot.quotes),
        len(symbols),
        (datetime.now(UTC) - started).total_seconds(),
    )

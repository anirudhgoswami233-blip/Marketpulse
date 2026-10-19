"""Earnings and IPO calendars (Finnhub), by Monday-to-Sunday week so every viewer shares one cached call."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import Fetched
from app.models import Symbol, Watchlist, WatchlistItem
from app.providers.base import EarningsEvent, IpoEvent, MarketDataProvider


def week_bounds(day: date) -> tuple[date, date]:
    monday = day - timedelta(days=day.weekday())
    return monday, monday + timedelta(days=6)


async def earnings_week(provider: MarketDataProvider, day: date) -> Fetched[list[EarningsEvent]]:
    start, end = week_bounds(day)
    return await provider.get_earnings_calendar(start, end)


async def ipos_week(provider: MarketDataProvider, day: date) -> Fetched[list[IpoEvent]]:
    start, end = week_bounds(day)
    return await provider.get_ipo_calendar(start, end)


async def company_names(session: AsyncSession, symbols: list[str]) -> dict[str, str]:
    if not symbols:
        return {}
    rows = await session.execute(
        select(Symbol.symbol, Symbol.description).where(
            Symbol.symbol.in_(symbols), Symbol.exchange_code == "US"
        )
    )
    return {symbol: description for symbol, description in rows.all()}


async def watchlist_symbols(session: AsyncSession, user_id: int) -> set[str]:
    rows = await session.execute(
        select(Symbol.symbol)
        .join(WatchlistItem, WatchlistItem.symbol_id == Symbol.id)
        .join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id)
        .where(Watchlist.user_id == user_id)
    )
    return set(rows.scalars().all())


def surprise_pct(actual: Decimal | None, estimate: Decimal | None) -> Decimal | None:
    """EPS surprise versus the estimate, in %. None when either side is missing or the estimate is zero."""
    if actual is None or estimate is None or estimate == 0:
        return None
    return ((actual - estimate) / abs(estimate) * 100).quantize(Decimal("0.1"))

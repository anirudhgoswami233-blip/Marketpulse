"""Daily price history, persisted in `price_bars` so each symbol costs one history call per trading day.

Only bars for completed sessions are stored; an in-progress daily bar would otherwise be frozen as final.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import CacheBackend, Fetched
from app.core.errors import ProviderError
from app.db import dialect_insert
from app.models import PriceBar, Symbol
from app.providers.base import Bar, Bars, Interval, MarketDataProvider
from app.services.market_hours import last_completed_session_date
from app.services.reference_data import exchange_schedules

logger = logging.getLogger(__name__)

FULL_HISTORY_BARS = 1300  # ~5 years of trading days; Twelve Data charts one credit regardless of size
TOPUP_PADDING_BARS = 5
RETRY_AFTER_FAILED_FETCH_S = 6 * 3600


async def get_daily_bars(
    session: AsyncSession,
    provider: MarketDataProvider,
    cache: CacheBackend,
    symbol: Symbol,
    since: date,
    now: datetime | None = None,
) -> Fetched[Bars]:
    now = now or datetime.now(UTC)
    schedule = exchange_schedules().get(symbol.exchange_code) or exchange_schedules()["US"]
    target = last_completed_session_date(schedule, now)
    latest = await _latest_bar_date(session, symbol.id)

    stale = False
    attempt_key = f"mp:history:attempted:{symbol.id}:{target.isoformat()}"
    if (latest is None or latest < target) and await cache.get(attempt_key) is None:
        try:
            fetched = await provider.get_bars(symbol.symbol, Interval.DAY_1, _outputsize(latest, target))
            await _store(session, symbol.id, fetched.data.bars, target, provider.name)
            await session.commit()
            latest = await _latest_bar_date(session, symbol.id)
        except ProviderError as exc:
            if latest is None:
                raise
            logger.warning("Daily history refresh failed for %s; serving stored bars: %s", symbol.symbol, exc)
            stale = True
        # Holidays and late data mean the provider may not have `target` yet: don't retry on every request.
        if latest is None or latest < target:
            await cache.set(attempt_key, "1", RETRY_AFTER_FAILED_FETCH_S)

    rows = (
        await session.execute(
            select(PriceBar)
            .where(PriceBar.symbol_id == symbol.id, PriceBar.date >= since)
            .order_by(PriceBar.date)
        )
    ).scalars()
    bars = [
        Bar(
            timestamp=datetime.combine(row.date, time(0), tzinfo=UTC),
            open=row.open,
            high=row.high,
            low=row.low,
            close=row.close,
            volume=row.volume,
        )
        for row in rows
    ]
    close = schedule.sessions[-1][1] if schedule.sessions else time(0)
    as_of = _session_close(latest, schedule.timezone, close) if latest else now
    return Fetched[Bars](
        data=Bars(
            symbol=symbol.symbol,
            interval=Interval.DAY_1,
            currency=symbol.currency,
            exchange_timezone=schedule.timezone,
            bars=bars,
        ),
        as_of=as_of,
        source="price_bars",
        stale=stale,
    )


def _outputsize(latest: date | None, target: date) -> int:
    if latest is None:
        return FULL_HISTORY_BARS
    return min(FULL_HISTORY_BARS, (target - latest).days + TOPUP_PADDING_BARS)


async def _latest_bar_date(session: AsyncSession, symbol_id: int) -> date | None:
    return (
        await session.execute(select(func.max(PriceBar.date)).where(PriceBar.symbol_id == symbol_id))
    ).scalar_one_or_none()


async def _store(session: AsyncSession, symbol_id: int, bars: list[Bar], up_to: date, source: str) -> None:
    rows = [
        {
            "symbol_id": symbol_id,
            "date": bar.timestamp.date(),
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
            "source": source,
        }
        for bar in bars
        if bar.timestamp.date() <= up_to
    ]
    if not rows:
        return
    insert = dialect_insert(session)
    for start in range(0, len(rows), 500):
        stmt = insert(PriceBar).values(rows[start : start + 500])
        stmt = stmt.on_conflict_do_update(
            index_elements=[PriceBar.symbol_id, PriceBar.date],
            set_={c: stmt.excluded[c] for c in ("open", "high", "low", "close", "volume", "source")},
        )
        await session.execute(stmt)


def _session_close(day: date, tz: str, close: time) -> datetime:
    return datetime.combine(day, close, tzinfo=ZoneInfo(tz)).astimezone(UTC)


def since_days(days: int, now: datetime | None = None) -> date:
    return (now or datetime.now(UTC)).date() - timedelta(days=days)

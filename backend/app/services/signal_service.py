"""Computes and stores signals: once per symbol per trading day, shared by the stock page and every brief.

Price history comes from `price_bars` (topped up at most once a day per symbol) and headlines from the
news provider's 15-minute cache, so recomputing is cheap and every API call goes through the limiter.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import CacheBackend
from app.core.errors import AppError, ProviderError
from app.db import dialect_insert
from app.models import SignalRecord, Symbol
from app.providers.base import Bar, MarketDataProvider
from app.services import history_service
from app.services.market_hours import last_completed_session_date
from app.services.reference_data import exchange_schedules
from app.services.search_service import price_available
from app.signals.engine import ENGINE_VERSION, DailyBar, SignalResult, evaluate

logger = logging.getLogger(__name__)

HISTORY_LOOKBACK_DAYS = 400  # ~275 sessions: enough for the 200-day average and the 52-week range
NEWS_LOOKBACK_DAYS = 7


class SignalsUnavailable(AppError):
    status, code = 503, "unavailable"


def to_daily_bars(bars: list[Bar]) -> list[DailyBar]:
    return [
        DailyBar(
            close=float(b.close),
            high=float(b.high),
            low=float(b.low),
            volume=float(b.volume) if b.volume is not None else None,
        )
        for b in bars
    ]


async def find_signal(session: AsyncSession, symbol_id: int, signal_date: date) -> SignalRecord | None:
    stmt = select(SignalRecord).where(
        SignalRecord.symbol_id == symbol_id,
        SignalRecord.signal_date == signal_date,
        SignalRecord.engine_version == ENGINE_VERSION,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_or_compute(
    session: AsyncSession,
    history: MarketDataProvider,
    news: MarketDataProvider,
    cache: CacheBackend,
    symbol: Symbol,
    now: datetime | None = None,
) -> SignalRecord:
    now = now or datetime.now(UTC)
    if not price_available(symbol):
        raise SignalsUnavailable(
            f"Signals need price history, which our data plan doesn't cover for {symbol.exchange_code}."
        )
    schedule = exchange_schedules().get(symbol.exchange_code) or exchange_schedules()["US"]
    target = last_completed_session_date(schedule, now)
    existing = await find_signal(session, symbol.id, target)
    if existing is not None:
        return existing

    try:
        fetched = await history_service.get_daily_bars(
            session, history, cache, symbol, target - timedelta(days=HISTORY_LOOKBACK_DAYS), now
        )
    except ProviderError as exc:
        raise SignalsUnavailable(
            "Price history is unavailable right now, so signals can't be computed."
        ) from exc
    bars = fetched.data.bars
    if not bars:
        raise SignalsUnavailable("No price history is available for this symbol yet.")
    # A holiday or late data means the newest bar may be older than `target`: label the signal by its data.
    signal_date = bars[-1].timestamp.date()
    existing = await find_signal(session, symbol.id, signal_date)
    if existing is not None:
        return existing

    headlines: list[str] | None
    if symbol.exchange_code != "US":
        # Company news only exists for listed companies; skip the call for forex/metals.
        result = evaluate(
            to_daily_bars(bars), None, news_skip_reason="News tone applies to US-listed companies only."
        )
        return await _store(session, symbol, signal_date, result, bars[-1].close)
    try:
        news_items = await news.get_company_news(
            symbol.symbol, signal_date - timedelta(days=NEWS_LOOKBACK_DAYS), now.date()
        )
        headlines = [n.headline for n in news_items.data]
    except ProviderError as exc:
        logger.info("Signals for %s computed without news: %s", symbol.symbol, exc)
        headlines = None

    result = evaluate(to_daily_bars(bars), headlines)
    return await _store(session, symbol, signal_date, result, bars[-1].close)


async def _store(
    session: AsyncSession, symbol: Symbol, signal_date: date, result: SignalResult, close: Decimal
) -> SignalRecord:
    insert = dialect_insert(session)
    stmt = (
        insert(SignalRecord)
        .values(
            symbol_id=symbol.id,
            signal_date=signal_date,
            engine_version=ENGINE_VERSION,
            score=result.score,
            label=result.label.value,
            reasons=[
                {"rule": s.rule, "direction": s.direction, "weight": s.weight, "reason": s.reason}
                for s in result.signals
            ],
            skipped=[{"rule": s.rule, "reason": s.reason} for s in result.skipped],
            indicators={k: round(v, 4) if v is not None else None for k, v in result.indicators.items()},
            price_at_signal=close,
            currency=symbol.currency,
            created_at=datetime.now(UTC),
        )
        # Two requests computing the same signal at once: keep the first, both read it back.
        .on_conflict_do_nothing(index_elements=["symbol_id", "signal_date", "engine_version"])
    )
    await session.execute(stmt)
    await session.commit()
    stored = await find_signal(session, symbol.id, signal_date)
    assert stored is not None
    logger.info("Signal %s %s: %s (%+d)", symbol.symbol, signal_date, stored.label, stored.score)
    return stored

"""Stock screener over the tracked large-cap universe (the markets-overview movers list).

Rows combine three things that are already paid for or cheap: quotes from the overview snapshot, the
latest stored technical signal, and fundamentals (profile + key metrics) refreshed by a background job
about once a day. A page load never triggers the ~60 provider calls the fundamentals need.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import CacheBackend
from app.core.errors import ProviderError
from app.core.ratelimit import background_priority
from app.models import SignalRecord, Symbol
from app.providers.base import MarketDataProvider
from app.schemas.markets import ScreenerOut, ScreenerRow
from app.services import markets_service
from app.services.reference_data import overview_config
from app.signals.engine import ENGINE_VERSION

logger = logging.getLogger(__name__)

FUNDAMENTALS_KEY = "mp:screener:fundamentals"
FUNDAMENTALS_TTL_S = 7 * 24 * 3600
FUNDAMENTALS_MAX_AGE = timedelta(hours=24)
SAVE_EVERY = 5
# A stored signal older than this isn't shown: it no longer describes the current chart.
SIGNAL_MAX_AGE_DAYS = 7
UNIVERSE_EXCHANGE = "US"


class Fundamentals(BaseModel):
    name: str | None = None
    industry: str | None = None
    market_cap: Decimal | None = None
    pe_ttm: Decimal | None = None
    eps_ttm: Decimal | None = None
    beta: Decimal | None = None
    dividend_yield_pct: Decimal | None = None
    week52_high: Decimal | None = None
    week52_low: Decimal | None = None
    fetched_at: datetime


class FundamentalsSnapshot(BaseModel):
    rows: dict[str, Fundamentals] = {}
    completed_at: datetime | None = None


def universe() -> list[str]:
    return list(overview_config().movers_universe)


async def load_fundamentals(cache: CacheBackend) -> FundamentalsSnapshot:
    raw = await cache.get(FUNDAMENTALS_KEY)
    if raw is None:
        return FundamentalsSnapshot()
    try:
        return FundamentalsSnapshot.model_validate_json(raw)
    except ValueError:
        logger.warning("Discarding unreadable screener fundamentals")
        return FundamentalsSnapshot()


async def save_fundamentals(cache: CacheBackend, snapshot: FundamentalsSnapshot) -> None:
    await cache.set(FUNDAMENTALS_KEY, snapshot.model_dump_json(), FUNDAMENTALS_TTL_S)


def needs_refresh(snapshot: FundamentalsSnapshot, now: datetime) -> bool:
    return snapshot.completed_at is None or now - snapshot.completed_at > FUNDAMENTALS_MAX_AGE


async def refresh_fundamentals(
    provider: MarketDataProvider, cache: CacheBackend, symbols: list[str] | None = None
) -> FundamentalsSnapshot:
    """Fetch profile + key metrics for every universe symbol at background priority (the limiter spreads
    the calls out). A symbol whose calls both fail keeps its previous row."""
    symbols = symbols if symbols is not None else universe()
    snapshot = await load_fundamentals(cache)
    with background_priority():
        for index, symbol in enumerate(symbols, start=1):
            profile = metrics = None
            try:
                profile = (await provider.get_company_profile(symbol)).data
            except ProviderError as exc:
                logger.info("Screener: profile for %s unavailable: %s", symbol, exc)
            try:
                metrics = (await provider.get_key_metrics(symbol)).data
            except ProviderError as exc:
                logger.info("Screener: metrics for %s unavailable: %s", symbol, exc)
            if profile is not None or metrics is not None:
                snapshot.rows[symbol] = Fundamentals(
                    name=profile.name if profile else None,
                    industry=profile.industry if profile else None,
                    market_cap=profile.market_cap if profile else None,
                    pe_ttm=metrics.pe_ttm if metrics else None,
                    eps_ttm=metrics.eps_ttm if metrics else None,
                    beta=metrics.beta if metrics else None,
                    dividend_yield_pct=metrics.dividend_yield_pct if metrics else None,
                    week52_high=metrics.week52_high if metrics else None,
                    week52_low=metrics.week52_low if metrics else None,
                    fetched_at=datetime.now(UTC),
                )
            if index % SAVE_EVERY == 0:
                await save_fundamentals(cache, snapshot)  # let the page fill in during the first warm-up
    snapshot.completed_at = datetime.now(UTC)
    await save_fundamentals(cache, snapshot)
    return snapshot


def week52_position_pct(price: Decimal | None, low: Decimal | None, high: Decimal | None) -> Decimal | None:
    """Where the price sits in its 52-week range: 0 = at the low, 100 = at the high."""
    if price is None or low is None or high is None or high <= low:
        return None
    position = (price - low) / (high - low) * 100
    return max(Decimal(0), min(Decimal(100), position)).quantize(Decimal("0.1"))


async def latest_signals(
    session: AsyncSession, symbol_ids: list[int], since: date
) -> dict[int, SignalRecord]:
    stmt = (
        select(SignalRecord)
        .where(
            SignalRecord.symbol_id.in_(symbol_ids),
            SignalRecord.engine_version == ENGINE_VERSION,
            SignalRecord.signal_date >= since,
        )
        .order_by(SignalRecord.signal_date.desc())
    )
    latest: dict[int, SignalRecord] = {}
    for record in (await session.execute(stmt)).scalars():
        latest.setdefault(record.symbol_id, record)
    return latest


async def get_screener(
    session: AsyncSession, cache: CacheBackend, now: datetime, refreshing: bool = False
) -> ScreenerOut:
    symbols = universe()
    quotes = await markets_service.load_snapshot(cache)
    fundamentals = await load_fundamentals(cache)
    directory = {
        row.symbol: row
        for row in await session.scalars(
            select(Symbol).where(Symbol.symbol.in_(symbols), Symbol.exchange_code == UNIVERSE_EXCHANGE)
        )
    }
    signals = await latest_signals(
        session, [s.id for s in directory.values()], now.date() - timedelta(days=SIGNAL_MAX_AGE_DAYS)
    )

    rows = []
    for symbol in symbols:
        listing = directory.get(symbol)
        if listing is None:
            continue  # not seeded yet: nothing to link to
        quote = quotes.quotes.get(symbol)
        facts = fundamentals.rows.get(symbol)
        signal = signals.get(listing.id)
        price = quote.price if quote else None
        rows.append(
            ScreenerRow(
                symbol=symbol,
                display_symbol=listing.display_symbol,
                name=(facts.name if facts and facts.name else listing.description),
                industry=facts.industry if facts else None,
                currency=listing.currency,
                price=price,
                change_pct=quote.change_pct if quote else None,
                market_cap=facts.market_cap if facts else None,
                pe_ttm=facts.pe_ttm if facts else None,
                eps_ttm=facts.eps_ttm if facts else None,
                beta=facts.beta if facts else None,
                dividend_yield_pct=facts.dividend_yield_pct if facts else None,
                week52_low=facts.week52_low if facts else None,
                week52_high=facts.week52_high if facts else None,
                week52_position_pct=week52_position_pct(
                    price, facts.week52_low if facts else None, facts.week52_high if facts else None
                ),
                signal_label=signal.label if signal else None,
                signal_score=signal.score if signal else None,
                signal_date=signal.signal_date if signal else None,
            )
        )

    return ScreenerOut(
        rows=rows,
        universe_size=len(symbols),
        pending_fundamentals=sum(1 for r in rows if r.symbol not in fundamentals.rows),
        refreshing=refreshing,
        quotes_as_of=quotes.updated_at,
        fundamentals_as_of=fundamentals.completed_at,
        stale=any(quotes.stale.get(r.symbol, False) for r in rows),
    )

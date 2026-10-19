"""Global markets overview: exchange status, index proxies by region, sector heatmap and top movers.

Quotes come from a snapshot that a background job refreshes at background priority (see
jobs/market_snapshot.py). Page loads never trigger the ~60 quote calls the overview needs.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from app.core.cache import CacheBackend
from app.core.errors import ProviderError
from app.core.ratelimit import background_priority
from app.providers.base import MarketDataProvider, Quote
from app.schemas.markets import (
    IndexCard,
    MarketOverview,
    MarketStatusOut,
    Mover,
    RegionOverview,
    SectorTile,
)
from app.services.market_hours import ExchangeSchedule, last_completed_session_date, status_at
from app.services.reference_data import OverviewConfig, exchange_schedules, overview_config

logger = logging.getLogger(__name__)

SNAPSHOT_KEY = "mp:overview:snapshot"
SNAPSHOT_TTL_S = 7 * 24 * 3600
MOVERS_COUNT = 5
SAVE_EVERY = 10
PROVIDER_STATUS_EXCHANGES = frozenset({"US"})  # Finnhub free tier: holiday-aware status for US only


class OverviewSnapshot(BaseModel):
    quotes: dict[str, Quote] = {}
    fetched_at: dict[str, datetime] = {}
    stale: dict[str, bool] = {}
    updated_at: datetime | None = None
    completed_at: datetime | None = None


async def load_snapshot(cache: CacheBackend) -> OverviewSnapshot:
    raw = await cache.get(SNAPSHOT_KEY)
    if raw is None:
        return OverviewSnapshot()
    try:
        return OverviewSnapshot.model_validate_json(raw)
    except ValueError:
        logger.warning("Discarding unreadable overview snapshot")
        return OverviewSnapshot()


async def save_snapshot(cache: CacheBackend, snapshot: OverviewSnapshot) -> None:
    await cache.set(SNAPSHOT_KEY, snapshot.model_dump_json(), SNAPSHOT_TTL_S)


async def market_statuses(
    provider: MarketDataProvider, now: datetime, codes: list[str] | None = None
) -> list[MarketStatusOut]:
    schedules = exchange_schedules()
    result = []
    for code in codes or list(schedules):
        schedule = schedules[code]
        result.append(await _status_for(provider, schedule, now))
    return result


async def _status_for(
    provider: MarketDataProvider, schedule: ExchangeSchedule, now: datetime
) -> MarketStatusOut:
    computed = status_at(schedule, now)
    out = MarketStatusOut(
        exchange=schedule.code,
        name=schedule.name,
        region=schedule.region,
        timezone=schedule.timezone,
        local_time=computed.local_time,
        is_open=computed.is_open,
        session=computed.session,
        holiday=None,
        next_change_at=computed.next_change_at,
        status_source="schedule",
    )
    if schedule.code not in PROVIDER_STATUS_EXCHANGES:
        return out
    try:
        live = (await provider.get_market_status(schedule.code)).data
    except ProviderError as exc:
        logger.info("Market status for %s unavailable, using schedule: %s", schedule.code, exc)
        return out
    return out.model_copy(
        update={
            "is_open": live.is_open,
            "session": live.session,
            "holiday": live.holiday,
            "status_source": "provider",
        }
    )


async def get_overview(
    provider: MarketDataProvider,
    cache: CacheBackend,
    now: datetime,
    stale_after: timedelta,
    config: OverviewConfig | None = None,
) -> MarketOverview:
    config = config or overview_config()
    snapshot = await load_snapshot(cache)
    quotes = snapshot.quotes

    region_codes = [code for r in config.regions for code in r.exchanges]
    statuses = {s.exchange: s for s in await market_statuses(provider, now, region_codes)}
    regions = [
        RegionOverview(
            region=r.region,
            markets=[statuses[c] for c in r.exchanges],
            indices=[
                IndexCard(symbol=i.symbol, name=i.name, tracks=i.tracks, quote=quotes.get(i.symbol))
                for i in r.indices
            ],
        )
        for r in config.regions
    ]
    sectors = [
        SectorTile(
            symbol=s.symbol,
            sector=s.sector,
            price=quotes[s.symbol].price if s.symbol in quotes else None,
            change_pct=quotes[s.symbol].change_pct if s.symbol in quotes else None,
        )
        for s in config.sectors
    ]
    gainers, losers = rank_movers([quotes[s] for s in config.movers_universe if s in quotes])

    pending = sum(1 for s in config.all_symbols() if s not in quotes)
    us_open = statuses["US"].is_open if "US" in statuses else True
    too_old = snapshot.updated_at is not None and us_open and now - snapshot.updated_at > stale_after
    return MarketOverview(
        regions=regions,
        sectors=sectors,
        gainers=gainers,
        losers=losers,
        movers_universe_size=len(config.movers_universe),
        as_of=snapshot.updated_at,
        stale=too_old or any(snapshot.stale.values()),
        pending_symbols=pending,
    )


def rank_movers(quotes: list[Quote], count: int = MOVERS_COUNT) -> tuple[list[Mover], list[Mover]]:
    priced = [q for q in quotes if q.change_pct is not None]
    by_change = sorted(priced, key=lambda q: q.change_pct or Decimal(0), reverse=True)

    def mover(q: Quote) -> Mover:
        assert q.change_pct is not None
        return Mover(
            symbol=q.symbol, price=q.price, change=q.change, change_pct=q.change_pct, currency=q.currency
        )

    gainers = [mover(q) for q in by_change if (q.change_pct or 0) > 0][:count]
    losers = [mover(q) for q in reversed(by_change) if (q.change_pct or 0) < 0][:count]
    return gainers, losers


async def should_refresh(
    provider: MarketDataProvider, cache: CacheBackend, now: datetime, closed_interval: timedelta
) -> bool:
    """Refresh during US trading hours; once closed, only until we hold a full post-close snapshot."""
    snapshot = await load_snapshot(cache)
    if snapshot.completed_at is None:
        return True
    us = (await market_statuses(provider, now, ["US"]))[0]
    if us.is_open:
        return True
    schedule = exchange_schedules()["US"]
    last_session = last_completed_session_date(schedule, now)
    close = datetime.combine(last_session, schedule.sessions[-1][1], tzinfo=ZoneInfo(schedule.timezone))
    if snapshot.completed_at < close.astimezone(UTC) + timedelta(minutes=5):
        return True  # still need the closing prices
    return now - snapshot.completed_at > closed_interval


async def refresh_snapshot(
    provider: MarketDataProvider,
    cache: CacheBackend,
    currencies: dict[str, str | None],
    config: OverviewConfig | None = None,
    symbols: list[str] | None = None,
) -> OverviewSnapshot:
    """Fetch overview quotes at background priority; the limiter spreads the calls out.

    With `symbols`, only those are fetched (a top-up) and the snapshot isn't marked complete, so the scheduled
    full refresh still runs.
    """
    config = config or overview_config()
    snapshot = await load_snapshot(cache)
    partial = symbols is not None
    symbols = symbols if symbols is not None else config.all_symbols()
    with background_priority():
        for index, symbol in enumerate(symbols, start=1):
            try:
                fetched = await provider.get_quote(symbol)
            except ProviderError as exc:
                logger.warning("Overview refresh: quote for %s failed: %s", symbol, exc)
            else:
                snapshot.quotes[symbol] = fetched.data.model_copy(update={"currency": currencies.get(symbol)})
                snapshot.fetched_at[symbol] = fetched.as_of
                snapshot.stale[symbol] = fetched.stale
                snapshot.updated_at = datetime.now(UTC)
            if index % SAVE_EVERY == 0:
                await save_snapshot(cache, snapshot)  # let pages show progress during the first warm-up
    if not partial:
        snapshot.completed_at = datetime.now(UTC)
    await save_snapshot(cache, snapshot)
    return snapshot


def missing_brief_symbols(snapshot: OverviewSnapshot, config: OverviewConfig | None = None) -> list[str]:
    """Regional index proxies and movers the Daily Brief needs that the snapshot doesn't have yet."""
    config = config or overview_config()
    needed = [i.symbol for r in config.regions for i in r.indices] + list(config.movers_universe)
    return [s for s in dict.fromkeys(needed) if s not in snapshot.quotes]

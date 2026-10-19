"""Forex & metals board: a few base pairs from Twelve Data, every other rate derived (no extra credits)."""

from __future__ import annotations

import logging
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from pydantic import BaseModel

from app.core.cache import CacheBackend, Fetched
from app.core.errors import ProviderError, RateLimitExceeded
from app.core.ratelimit import background_priority
from app.providers.base import MarketDataProvider, Quote
from app.services.fx_math import PairQuote, cross, usd_values
from app.services.market_hours import status_at
from app.services.reference_data import ForexConfig, exchange_schedules, forex_config

logger = logging.getLogger(__name__)

SNAPSHOT_KEY = "mp:forex:snapshot"
SNAPSHOT_TTL_S = 7 * 24 * 3600


class StoredPair(BaseModel):
    rate: Decimal
    prev_close: Decimal | None
    fetched_at: datetime


class FxSnapshot(BaseModel):
    pairs: dict[str, StoredPair] = {}
    completed_at: datetime | None = None


async def load_snapshot(cache: CacheBackend) -> FxSnapshot:
    raw = await cache.get(SNAPSHOT_KEY)
    if raw is None:
        return FxSnapshot()
    try:
        return FxSnapshot.model_validate_json(raw)
    except ValueError:
        logger.warning("Discarding unreadable forex snapshot")
        return FxSnapshot()


def needs_refresh(snapshot: FxSnapshot, now: datetime, interval: timedelta) -> bool:
    """Refresh while forex trades; over the weekend only until we hold a post-close snapshot."""
    if snapshot.completed_at is None:
        return True
    age = now - snapshot.completed_at
    status = status_at(exchange_schedules()["OANDA"], now)
    if status.is_open:
        return age >= interval * 0.9  # small slack so an hourly job doesn't skip a run on timing jitter
    # Closed: next_change_at is Sunday's reopen; the close was two days before it.
    reopen = status.next_change_at
    last_close = reopen - timedelta(days=2) if reopen else now
    return snapshot.completed_at < last_close


async def refresh(
    provider: MarketDataProvider,
    cache: CacheBackend,
    config: ForexConfig | None = None,
    *,
    background: bool = True,
) -> FxSnapshot:
    """Fetch the base pairs. Scheduled refreshes run at background priority; a warm-up triggered by someone
    opening the page (`background=False`) uses the interactive budget so rates appear sooner."""
    config = config or forex_config()
    snapshot = await load_snapshot(cache)
    for pair in config.base_pairs:
        try:
            try:
                with background_priority() if background else nullcontext():
                    fetched = await provider.get_quote(pair)  # Twelve Data takes "EUR/USD" as-is
            except RateLimitExceeded:
                if background:
                    raise
                # The interactive budget for this minute is spent: finish at background priority, which
                # waits for the next window instead of giving up after a few seconds.
                background = True
                with background_priority():
                    fetched = await provider.get_quote(pair)
        except ProviderError as exc:
            logger.warning("Forex refresh: %s failed: %s", pair, exc)
            continue
        snapshot.pairs[pair] = StoredPair(
            rate=fetched.data.price, prev_close=fetched.data.prev_close, fetched_at=fetched.as_of
        )
        # Save as we go: the limiter spreads these calls over a couple of minutes, and the board can show
        # each rate as soon as it arrives instead of waiting for all of them.
        await cache.set(SNAPSHOT_KEY, snapshot.model_dump_json(), SNAPSHOT_TTL_S)
    snapshot.completed_at = datetime.now(UTC)
    await cache.set(SNAPSHOT_KEY, snapshot.model_dump_json(), SNAPSHOT_TTL_S)
    logger.info("Forex snapshot refreshed: %d/%d base pairs", len(snapshot.pairs), len(config.base_pairs))
    return snapshot


class BoardRow(BaseModel):
    pair: str
    group: str
    symbol: str | None
    rate: Decimal | None
    change_pct: Decimal | None
    derived: bool


class ForexBoard(BaseModel):
    rows: list[BoardRow]
    # USD per one unit of each currency/metal, for the converter.
    usd_per_unit: dict[str, Decimal]
    currencies: list[dict[str, str]]
    as_of: datetime | None
    stale: bool
    refreshing: bool
    refresh_interval_min: int


def build_board(
    snapshot: FxSnapshot,
    now: datetime,
    interval: timedelta,
    refreshing: bool,
    config: ForexConfig | None = None,
) -> ForexBoard:
    config = config or forex_config()
    values = usd_values({p: PairQuote(s.rate, s.prev_close) for p, s in snapshot.pairs.items()})
    rows = []
    for entry in config.board:
        rate = cross(entry.pair, values)
        rows.append(
            BoardRow(
                pair=entry.pair,
                group=entry.group,
                symbol=entry.symbol,
                rate=rate.rate if rate else None,
                change_pct=rate.change_pct if rate else None,
                derived=entry.pair not in config.base_pairs,
            )
        )
    oldest = min((s.fetched_at for s in snapshot.pairs.values()), default=None)
    is_open = status_at(exchange_schedules()["OANDA"], now).is_open
    stale = oldest is not None and is_open and now - oldest > interval * 2
    return ForexBoard(
        rows=rows,
        usd_per_unit={code: v.now for code, v in values.items()},
        currencies=[{"code": c, "name": n} for c, n in config.currencies],
        as_of=snapshot.completed_at or max((s.fetched_at for s in snapshot.pairs.values()), default=None),
        stale=stale,
        refreshing=refreshing,
        refresh_interval_min=int(interval.total_seconds() // 60),
    )


def pair_for(symbol_code: str) -> str | None:
    """ "OANDA:XAU_USD" / "FX:USD_INR" -> "XAU/USD" / "USD/INR"."""
    _, _, tail = symbol_code.partition(":")
    base, _, counter = tail.partition("_")
    return f"{base}/{counter}" if len(base) == 3 and len(counter) == 3 else None


async def quote_from_snapshot(
    cache: CacheBackend, symbol_code: str, max_age: timedelta, now: datetime | None = None
) -> Fetched[Quote] | None:
    """A quote for a forex/metal symbol from the board snapshot (base pairs and derived crosses), if it covers
    the pair and is recent. Saves a Twelve Data credit per page view; None means "ask the provider"."""
    pair = pair_for(symbol_code)
    if pair is None:
        return None
    now = now or datetime.now(UTC)
    snapshot = await load_snapshot(cache)
    fresh = {p: s for p, s in snapshot.pairs.items() if now - s.fetched_at <= max_age}
    values = usd_values({p: PairQuote(s.rate, s.prev_close) for p, s in fresh.items()})
    rate = cross(pair, values)
    if rate is None:
        return None
    base, counter = pair.split("/")
    prev = None
    if values[base].prev and values[counter].prev:
        prev = (values[base].prev / values[counter].prev).quantize(Decimal("1e-8"))  # type: ignore[operator]
    legs = [s.fetched_at for p, s in fresh.items() if base in p or counter in p] or [now]
    quote = Quote(
        symbol=symbol_code,
        price=rate.rate,
        change=(rate.rate - prev) if prev is not None else None,
        change_pct=rate.change_pct,
        open=None,
        high=None,
        low=None,
        prev_close=prev,
        timestamp=min(legs),
    )
    return Fetched[Quote](data=quote, as_of=min(legs), source="twelvedata (board)")

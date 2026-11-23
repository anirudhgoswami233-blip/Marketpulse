"""Per-user "what matters" news digest: material headlines across a user's watched symbols.

Like the screener, it serves a cached snapshot and starts a bounded background refresh when stale, so a
large watchlist never bursts the provider budget — company-news calls go through the limiter at background
priority and mostly hit the shared 15-minute cache. Reuses the Phase 1 classifier; descriptive only.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import CacheBackend
from app.core.errors import ProviderError
from app.core.ratelimit import background_priority
from app.models import Symbol, Watchlist, WatchlistItem
from app.providers.base import MarketDataProvider
from app.schemas.portfolio import WatchlistNewsItem, WatchlistNewsOut
from app.services import news_service, stock_service

logger = logging.getLogger(__name__)

DIGEST_TTL_S = 30 * 60
DIGEST_MAX_AGE = timedelta(minutes=15)  # matches the company-news cache TTL
MAX_DIGEST_SYMBOLS = 25  # a cold refresh never fetches more than this many symbols' news
MAX_DIGEST_ITEMS = 40
SAVE_EVERY = 5  # persist partway through a cold refresh so the panel fills in


class DigestSnapshot(BaseModel):
    items: list[dict[str, str]] = []  # news_service.NewsHighlight.to_dict()
    symbols_total: int = 0
    symbols_done: int = 0
    completed_at: datetime | None = None


def _key(user_id: int) -> str:
    return f"mp:wl-news:{user_id}"


async def load_digest(cache: CacheBackend, user_id: int) -> DigestSnapshot:
    raw = await cache.get(_key(user_id))
    if raw is None:
        return DigestSnapshot()
    try:
        return DigestSnapshot.model_validate_json(raw)
    except ValueError:
        logger.warning("Discarding unreadable watchlist news digest for user %s", user_id)
        return DigestSnapshot()


async def save_digest(cache: CacheBackend, user_id: int, snapshot: DigestSnapshot) -> None:
    await cache.set(_key(user_id), snapshot.model_dump_json(), DIGEST_TTL_S)


def needs_refresh(snapshot: DigestSnapshot, now: datetime) -> bool:
    return snapshot.completed_at is None or now - snapshot.completed_at > DIGEST_MAX_AGE


async def watched_symbols(session: AsyncSession, user_id: int) -> list[Symbol]:
    """Distinct US-listed symbols across the user's watchlists (company news is US-only), capped."""
    rows = (
        (
            await session.execute(
                select(Symbol)
                .join(WatchlistItem, WatchlistItem.symbol_id == Symbol.id)
                .join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id)
                .where(Watchlist.user_id == user_id)
                .order_by(Watchlist.sort_order, WatchlistItem.sort_order, WatchlistItem.id)
            )
        )
        .scalars()
        .all()
    )
    chosen: dict[int, Symbol] = {}
    for symbol in rows:
        if symbol.exchange_code == "US" and symbol.id not in chosen:
            chosen[symbol.id] = symbol
        if len(chosen) >= MAX_DIGEST_SYMBOLS:
            break
    return list(chosen.values())


def _top(highlights: list[news_service.NewsHighlight]) -> list[dict[str, str]]:
    return [h.to_dict() for h in news_service.sort_highlights(highlights)[:MAX_DIGEST_ITEMS]]


async def refresh_digest(
    provider: MarketDataProvider,
    cache: CacheBackend,
    user_id: int,
    symbols: list[Symbol],
    now: datetime,
) -> DigestSnapshot:
    """Fetch and classify each watched symbol's news at background priority, newest/most-material first."""
    snapshot = DigestSnapshot(symbols_total=len(symbols))
    collected: list[news_service.NewsHighlight] = []
    with background_priority():
        for index, symbol in enumerate(symbols, start=1):
            try:
                fetched = await stock_service.get_news(provider, symbol, now.date())
            except ProviderError as exc:
                logger.info("Digest: news for %s unavailable: %s", symbol.symbol, exc)
            else:
                collected.extend(news_service.material_headlines(symbol, fetched.data))
            snapshot.symbols_done = index
            if index % SAVE_EVERY == 0:
                snapshot.items = _top(collected)
                await save_digest(cache, user_id, snapshot)  # let the panel fill in during warm-up
    snapshot.items = _top(collected)
    snapshot.completed_at = now
    await save_digest(cache, user_id, snapshot)
    return snapshot


async def get_digest(
    session: AsyncSession, cache: CacheBackend, user_id: int, now: datetime, refreshing: bool
) -> WatchlistNewsOut:
    snapshot = await load_digest(cache, user_id)
    # Filter to currently-watched symbols so a just-removed symbol's news drops out at once.
    watched = {symbol.symbol for symbol in await watched_symbols(session, user_id)}
    items = [WatchlistNewsItem(**item) for item in snapshot.items if item["symbol"] in watched]
    pending = max(0, snapshot.symbols_total - snapshot.symbols_done) if refreshing else 0
    return WatchlistNewsOut(
        items=items,
        refreshing=refreshing,
        symbols_total=len(watched),
        symbols_pending=pending,
        as_of=snapshot.completed_at,
        stale=needs_refresh(snapshot, now),
    )

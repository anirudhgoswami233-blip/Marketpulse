"""Company news enriched with an event classification and the stock's own reaction to each headline.

Descriptive only: categories and reactions explain what happened, never what to do. All data comes through
the provider -> rate limiter -> cache path; reactions reuse the daily bars we already store, so classifying
news adds no new provider call beyond the existing news fetch.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import CacheBackend, Fetched
from app.core.errors import ProviderError
from app.models import Symbol
from app.providers.base import MarketDataProvider, NewsItem
from app.schemas.markets import NewsImpactOut, NewsItemOut, NewsReactionOut
from app.services import history_service, stock_service
from app.signals import news_impact
from app.signals.reactions import NextSessionMove, next_session_move

logger = logging.getLogger(__name__)

# How far back to pull daily bars so the oldest headline (NEWS_LOOKBACK_DAYS old) still has a reference and
# a following session, with slack for weekends/holidays.
BARS_LOOKBACK_DAYS = stock_service.NEWS_LOOKBACK_DAYS + 21


async def get_stock_news(
    session: AsyncSession,
    news_provider: MarketDataProvider,
    history_provider: MarketDataProvider,
    cache: CacheBackend,
    symbol: Symbol,
    now: datetime | None = None,
) -> Fetched[list[NewsItemOut]]:
    now = now or datetime.now(UTC)
    fetched = await stock_service.get_news(news_provider, symbol, now.date())
    bars = await _reaction_bars(session, history_provider, cache, symbol, now)

    items = [_classify(item, bars) for item in fetched.data]
    return Fetched[list[NewsItemOut]](
        data=items, as_of=fetched.as_of, source=fetched.source, stale=fetched.stale
    )


def _classify(item: NewsItem, bars: list[tuple[date, Decimal]]) -> NewsItemOut:
    reaction: NextSessionMove | None = next_session_move(bars, item.published_at.date()) if bars else None
    impact = news_impact.classify(
        item.headline, item.summary, price_change_pct=reaction.move_pct if reaction else None
    )
    return NewsItemOut(
        **item.model_dump(),
        impact=NewsImpactOut(
            category=impact.category.value,
            category_label=news_impact.CATEGORY_LABELS[impact.category],
            materiality=impact.materiality.value,
            tone=impact.tone,
        ),
        reaction=(
            NewsReactionOut(
                ref_date=reaction.ref_date, next_date=reaction.next_date, move_pct=reaction.move_pct
            )
            if reaction
            else None
        ),
    )


async def _reaction_bars(
    session: AsyncSession,
    provider: MarketDataProvider,
    cache: CacheBackend,
    symbol: Symbol,
    now: datetime,
) -> list[tuple[date, Decimal]]:
    """Daily (date, close) pairs for reaction math, oldest first. Best-effort: reactions are a nicety, so a
    missing or failing history source just means no reaction line — never a broken news list."""
    if symbol.exchange_code != "US":  # company news reactions only apply to US-listed equities
        return []
    since = now.date() - timedelta(days=BARS_LOOKBACK_DAYS)
    try:
        fetched = await history_service.get_daily_bars(session, provider, cache, symbol, since, now)
    except ProviderError as exc:
        logger.info("News reactions skipped for %s: %s", symbol.symbol, exc)
        return []
    return [(bar.timestamp.date(), bar.close) for bar in fetched.data.bars]

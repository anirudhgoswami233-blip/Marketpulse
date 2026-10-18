"""Stock detail data: profile, key metrics, news and price charts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import CacheBackend, Fetched
from app.models import Symbol
from app.providers.base import Bar, CompanyProfile, Interval, KeyMetrics, MarketDataProvider, NewsItem
from app.schemas.markets import ChartOut
from app.services import history_service
from app.services.reference_data import exchange_schedules

NEWS_LOOKBACK_DAYS = 7
NEWS_LIMIT = 20


class ChartRange(StrEnum):
    D1 = "1D"
    W1 = "1W"
    M1 = "1M"
    Y1 = "1Y"
    Y5 = "5Y"


@dataclass(frozen=True)
class RangeSpec:
    interval: Interval
    intraday_bars: int = 0  # how many intraday bars to request
    sessions: int = 0  # how many most-recent trading sessions to keep (intraday)
    days: int = 0  # calendar-day lookback (daily)


RANGES: dict[ChartRange, RangeSpec] = {
    # 5-minute bars: two sessions' worth (78/day) so a pre-market request still has the last full day.
    ChartRange.D1: RangeSpec(Interval.MIN_5, intraday_bars=160, sessions=1),
    ChartRange.W1: RangeSpec(Interval.MIN_30, intraday_bars=100, sessions=5),
    ChartRange.M1: RangeSpec(Interval.DAY_1, days=31),
    ChartRange.Y1: RangeSpec(Interval.DAY_1, days=366),
    ChartRange.Y5: RangeSpec(Interval.DAY_1, days=5 * 366),
}


async def get_profile(provider: MarketDataProvider, symbol: Symbol) -> Fetched[CompanyProfile]:
    return await provider.get_company_profile(symbol.symbol)


async def get_metrics(provider: MarketDataProvider, symbol: Symbol) -> Fetched[KeyMetrics]:
    return await provider.get_key_metrics(symbol.symbol)


async def get_news(
    provider: MarketDataProvider, symbol: Symbol, today: date | None = None
) -> Fetched[list[NewsItem]]:
    today = today or datetime.now(UTC).date()
    fetched = await provider.get_company_news(
        symbol.symbol, today - timedelta(days=NEWS_LOOKBACK_DAYS), today
    )
    latest = sorted(fetched.data, key=lambda n: n.published_at, reverse=True)[:NEWS_LIMIT]
    return fetched.model_copy(update={"data": latest})


async def get_chart(
    session: AsyncSession,
    provider: MarketDataProvider,
    cache: CacheBackend,
    symbol: Symbol,
    chart_range: ChartRange,
    now: datetime | None = None,
) -> Fetched[ChartOut]:
    now = now or datetime.now(UTC)
    spec = RANGES[chart_range]
    schedule = exchange_schedules().get(symbol.exchange_code) or exchange_schedules()["US"]

    if spec.interval is Interval.DAY_1:
        daily = await history_service.get_daily_bars(
            session, provider, cache, symbol, now.date() - timedelta(days=spec.days), now
        )
        bars, as_of, source, stale = daily.data.bars, daily.as_of, daily.source, daily.stale
        timezone = daily.data.exchange_timezone
    else:
        intraday = await provider.get_bars(symbol.symbol, spec.interval, spec.intraday_bars)
        timezone = intraday.data.exchange_timezone or schedule.timezone
        bars = last_sessions(intraday.data.bars, spec.sessions, timezone)
        as_of, source, stale = intraday.as_of, intraday.source, intraday.stale

    return Fetched[ChartOut](
        data=ChartOut(
            symbol=symbol.symbol,
            range=chart_range.value,
            interval=spec.interval.value,
            currency=symbol.currency,
            timezone=timezone,
            bars=bars,
        ),
        as_of=as_of,
        source=source,
        stale=stale,
    )


def last_sessions(bars: list[Bar], sessions: int, timezone: str) -> list[Bar]:
    """Keep bars from the most recent `sessions` local trading dates."""
    tz = ZoneInfo(timezone)
    dates = sorted({b.timestamp.astimezone(tz).date() for b in bars})
    keep = set(dates[-sessions:])
    return [b for b in bars if b.timestamp.astimezone(tz).date() in keep]

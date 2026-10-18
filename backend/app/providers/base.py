"""Vendor-neutral provider interface and data models.

Adapters map raw vendor JSON into these models; nothing vendor-specific crosses this boundary.
Every public method returns `Fetched[T]` (data + as_of + source + stale), produced by `@cached`.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel

from app.core.cache import CacheBackend, Fetched
from app.core.errors import ProviderUnavailable


class Quote(BaseModel):
    symbol: str
    price: Decimal
    change: Decimal | None
    change_pct: Decimal | None
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    prev_close: Decimal | None
    timestamp: datetime | None
    # Not every vendor returns currency on a quote; services fill it from the symbol directory.
    currency: str | None = None


class SymbolMatch(BaseModel):
    symbol: str
    display_symbol: str
    description: str
    type: str


class SymbolRecord(BaseModel):
    symbol: str
    display_symbol: str
    description: str
    type: str
    currency: str | None
    mic: str | None
    figi: str | None


class ForexSymbol(BaseModel):
    symbol: str
    display_symbol: str
    description: str


class CompanyProfile(BaseModel):
    symbol: str
    name: str
    country: str | None
    currency: str | None
    exchange: str | None
    industry: str | None
    ipo_date: date | None
    logo_url: str | None
    website: str | None
    market_cap: Decimal | None
    shares_outstanding: Decimal | None


class KeyMetrics(BaseModel):
    symbol: str
    week52_high: Decimal | None
    week52_high_date: date | None
    week52_low: Decimal | None
    week52_low_date: date | None
    pe_ttm: Decimal | None
    eps_ttm: Decimal | None
    pb: Decimal | None
    ps_ttm: Decimal | None
    beta: Decimal | None
    dividend_yield_pct: Decimal | None
    roe_ttm_pct: Decimal | None
    net_margin_ttm_pct: Decimal | None
    revenue_growth_ttm_yoy_pct: Decimal | None
    avg_volume_10d: Decimal | None
    avg_volume_3m: Decimal | None


class NewsItem(BaseModel):
    id: str
    headline: str
    summary: str
    source: str
    url: str
    image_url: str | None
    published_at: datetime
    category: str | None
    related_symbols: list[str]


class EarningsSession(StrEnum):
    BEFORE_OPEN = "before_open"
    AFTER_CLOSE = "after_close"
    DURING_MARKET = "during_market"
    UNKNOWN = "unknown"


class EarningsEvent(BaseModel):
    symbol: str
    date: date
    session: EarningsSession
    quarter: int | None
    year: int | None
    eps_estimate: Decimal | None
    eps_actual: Decimal | None
    revenue_estimate: Decimal | None
    revenue_actual: Decimal | None


class IpoEvent(BaseModel):
    symbol: str | None
    name: str
    date: date
    exchange: str | None
    status: str | None
    price_range: str | None
    shares: int | None
    total_value: Decimal | None


class MarketSession(StrEnum):
    PRE_MARKET = "pre_market"
    REGULAR = "regular"
    POST_MARKET = "post_market"
    CLOSED = "closed"


class MarketStatus(BaseModel):
    exchange: str
    is_open: bool
    session: MarketSession
    holiday: str | None
    timezone: str | None
    timestamp: datetime | None


class MarketHoliday(BaseModel):
    name: str
    date: date
    trading_hours: str | None


class Bar(BaseModel):
    """One OHLCV bar. `timestamp` is the bar open in UTC (daily bars: midnight UTC of the trading date)."""

    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int | None


class Interval(StrEnum):
    MIN_5 = "5min"
    MIN_30 = "30min"
    HOUR_1 = "1h"
    DAY_1 = "1day"
    WEEK_1 = "1week"


class Bars(BaseModel):
    symbol: str
    interval: Interval
    currency: str | None
    exchange_timezone: str | None
    bars: list[Bar]


class ForexRate(BaseModel):
    base: str
    quote: str
    rate: Decimal
    timestamp: datetime | None


class MacroObservation(BaseModel):
    date: date
    value: Decimal


class MacroSeries(BaseModel):
    series_id: str
    title: str
    units: str
    frequency: str
    last_updated: datetime | None
    observations: list[MacroObservation]


def _unsupported(provider: str, capability: str) -> ProviderUnavailable:
    return ProviderUnavailable(provider, f"{capability} is not supported by this provider")


class MarketDataProvider:
    """Interface for market data. Adapters override what their plan supports; the rest raise
    ProviderUnavailable.

    Which provider serves each capability is decided in `providers/registry.py`, based on
    docs/finnhub-endpoints.md.
    """

    name: str
    cache: CacheBackend

    async def get_quote(self, symbol: str) -> Fetched[Quote]:
        raise _unsupported(self.name, "quotes")

    async def search_symbols(self, query: str) -> Fetched[list[SymbolMatch]]:
        raise _unsupported(self.name, "symbol search")

    async def list_symbols(self, exchange: str) -> Fetched[list[SymbolRecord]]:
        raise _unsupported(self.name, "symbol lists")

    async def list_forex_symbols(self, exchange: str) -> Fetched[list[ForexSymbol]]:
        raise _unsupported(self.name, "forex symbols")

    async def get_company_profile(self, symbol: str) -> Fetched[CompanyProfile]:
        raise _unsupported(self.name, "company profiles")

    async def get_key_metrics(self, symbol: str) -> Fetched[KeyMetrics]:
        raise _unsupported(self.name, "key metrics")

    async def get_company_news(self, symbol: str, start: date, end: date) -> Fetched[list[NewsItem]]:
        raise _unsupported(self.name, "company news")

    async def get_market_news(self, category: str = "general") -> Fetched[list[NewsItem]]:
        raise _unsupported(self.name, "market news")

    async def get_earnings_calendar(self, start: date, end: date) -> Fetched[list[EarningsEvent]]:
        raise _unsupported(self.name, "earnings calendar")

    async def get_ipo_calendar(self, start: date, end: date) -> Fetched[list[IpoEvent]]:
        raise _unsupported(self.name, "IPO calendar")

    async def get_market_status(self, exchange: str) -> Fetched[MarketStatus]:
        raise _unsupported(self.name, "market status")

    async def get_market_holidays(self, exchange: str) -> Fetched[list[MarketHoliday]]:
        raise _unsupported(self.name, "market holidays")

    async def get_bars(self, symbol: str, interval: Interval, outputsize: int) -> Fetched[Bars]:
        raise _unsupported(self.name, "price history")

    async def get_forex_rate(self, base: str, quote: str) -> Fetched[ForexRate]:
        raise _unsupported(self.name, "forex rates")


class MacroDataProvider:
    name: str
    cache: CacheBackend

    async def get_series(self, series_id: str, start: date) -> Fetched[MacroSeries]:
        raise _unsupported(self.name, "macro series")

"""In-memory provider doubles for service tests (no HTTP, no caching)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal

from app.core.cache import Fetched, MemoryCache
from app.core.errors import ProviderUnavailable
from app.core.ratelimit import Priority, current_priority
from app.providers.base import (
    Bar,
    Bars,
    CompanyProfile,
    Interval,
    MarketDataProvider,
    MarketSession,
    MarketStatus,
    NewsItem,
    Quote,
)

NOW = datetime(2026, 10, 19, 15, 0, tzinfo=UTC)


def make_quote(
    symbol: str, price: str, change_pct: str | None = "0", prev_close: str | None = "100"
) -> Quote:
    p = Decimal(price)
    prev = Decimal(prev_close) if prev_close else None
    return Quote(
        symbol=symbol,
        price=p,
        change=p - prev if prev else None,
        change_pct=Decimal(change_pct) if change_pct is not None else None,
        open=None,
        high=p,
        low=p,
        prev_close=prev,
        timestamp=datetime(2026, 10, 19, 14, 0, tzinfo=UTC),
    )


def daily_bar(day: date, close: str = "100") -> Bar:
    c = Decimal(close)
    return Bar(
        timestamp=datetime.combine(day, datetime.min.time(), tzinfo=UTC),
        open=c,
        high=c,
        low=c,
        close=c,
        volume=1000,
    )


class FakeProvider(MarketDataProvider):
    name = "fake"

    def __init__(self) -> None:
        self.cache = MemoryCache()
        self.quotes: dict[str, Quote] = {}
        self.quote_errors: dict[str, Exception] = {}
        self.quote_priorities: list[Priority] = []
        self.status: MarketStatus | Exception = ProviderUnavailable("fake", "no status")
        self.bars: Callable[[str, Interval, int], list[Bar]] | Exception | None = None
        self.bars_calls: list[tuple[str, Interval, int]] = []
        self.news: list[NewsItem] = []
        self.as_of = NOW

    def _wrap[T](self, data: T) -> Fetched[T]:
        return Fetched[T](data=data, as_of=self.as_of, source=self.name)

    async def get_quote(self, symbol: str) -> Fetched[Quote]:
        self.quote_priorities.append(current_priority())
        if symbol in self.quote_errors:
            raise self.quote_errors[symbol]
        if symbol not in self.quotes:
            raise ProviderUnavailable(self.name, f"no quote for {symbol}")
        return self._wrap(self.quotes[symbol])

    async def get_market_status(self, exchange: str) -> Fetched[MarketStatus]:
        if isinstance(self.status, Exception):
            raise self.status
        return self._wrap(self.status)

    async def get_bars(self, symbol: str, interval: Interval, outputsize: int) -> Fetched[Bars]:
        self.bars_calls.append((symbol, interval, outputsize))
        if isinstance(self.bars, Exception):
            raise self.bars
        assert self.bars is not None, "set FakeProvider.bars"
        return self._wrap(
            Bars(
                symbol=symbol,
                interval=interval,
                currency="USD",
                exchange_timezone="America/New_York",
                bars=self.bars(symbol, interval, outputsize),
            )
        )

    async def get_company_news(self, symbol: str, start: date, end: date) -> Fetched[list[NewsItem]]:
        return self._wrap(self.news)

    async def get_company_profile(self, symbol: str) -> Fetched[CompanyProfile]:
        raise ProviderUnavailable(self.name, "no profiles")


def open_us_status() -> MarketStatus:
    return MarketStatus(
        exchange="US",
        is_open=True,
        session=MarketSession.REGULAR,
        holiday=None,
        timezone="America/New_York",
        timestamp=NOW,
    )

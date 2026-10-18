"""Finnhub adapter (primary provider). The only module allowed to talk to Finnhub's REST API.

Free-tier availability is recorded in docs/finnhub-endpoints.md. Price history (candles), non-US
quotes, forex rates and news sentiment are premium, so this adapter doesn't implement them.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.core.cache import CacheBackend, cached
from app.core.errors import NoDataError, ProviderError, ProviderUnavailable
from app.core.ratelimit import RateLimiter
from app.providers.base import (
    CompanyProfile,
    EarningsEvent,
    EarningsSession,
    ForexSymbol,
    IpoEvent,
    KeyMetrics,
    MarketDataProvider,
    MarketHoliday,
    MarketSession,
    MarketStatus,
    NewsItem,
    Quote,
    SymbolMatch,
    SymbolRecord,
)
from app.providers.http import ProviderTransport

BASE_URL = "https://finnhub.io/api/v1"

TTL_QUOTE = 60
TTL_MARKET_STATUS = 5 * 60
TTL_NEWS = 15 * 60
TTL_CALENDAR = 6 * 3600
TTL_REFERENCE = 24 * 3600
TTL_SYMBOL_LIST = 7 * 24 * 3600

MILLION = Decimal(1_000_000)

_EARNINGS_HOUR = {
    "bmo": EarningsSession.BEFORE_OPEN,
    "amc": EarningsSession.AFTER_CLOSE,
    "dmh": EarningsSession.DURING_MARKET,
}
_SESSION = {
    "pre-market": MarketSession.PRE_MARKET,
    "regular": MarketSession.REGULAR,
    "post-market": MarketSession.POST_MARKET,
}


def build_client(api_key: str, timeout_s: float = 20.0) -> httpx.AsyncClient:
    # The key goes in a header so it never appears in URLs or access logs.
    return httpx.AsyncClient(base_url=BASE_URL, headers={"X-Finnhub-Token": api_key}, timeout=timeout_s)


class FinnhubProvider(MarketDataProvider):
    name = "finnhub"

    def __init__(self, client: httpx.AsyncClient, limiter: RateLimiter, cache: CacheBackend) -> None:
        self.cache = cache
        self._http = ProviderTransport(self.name, client, limiter)

    async def _get(
        self, path: str, params: dict[str, str | int] | None = None, *, follow_redirects: bool = False
    ) -> Any:
        payload = await self._http.get_json(path, params, follow_redirects=follow_redirects)
        # Finnhub sometimes answers 200 with {"error": "..."} (e.g. CFD index quotes on the free tier).
        if isinstance(payload, dict) and isinstance(payload.get("error"), str):
            message = payload["error"]
            if "access" in message.lower() or "subscription" in message.lower():
                raise ProviderUnavailable(self.name, f"{path}: {message}")
            raise ProviderError(self.name, f"{path}: {message}")
        return payload

    @cached(ttl=TTL_QUOTE)
    async def get_quote(self, symbol: str) -> Quote:
        raw = _expect_dict(await self._get("/quote", {"symbol": symbol}), "/quote")
        # Unknown symbols come back as all zeros rather than an error.
        if not raw.get("c") and not raw.get("pc"):
            raise NoDataError(self.name, f"no quote for {symbol}")
        return Quote(
            symbol=symbol,
            price=_require_dec(raw.get("c"), "/quote c"),
            change=_dec(raw.get("d")),
            change_pct=_dec(raw.get("dp")),
            open=_dec(raw.get("o")),
            high=_dec(raw.get("h")),
            low=_dec(raw.get("l")),
            prev_close=_dec(raw.get("pc")),
            timestamp=_ts(raw.get("t")),
        )

    @cached(ttl=TTL_REFERENCE)
    async def search_symbols(self, query: str) -> list[SymbolMatch]:
        raw = _expect_dict(await self._get("/search", {"q": query}), "/search")
        return [
            SymbolMatch(
                symbol=item["symbol"],
                display_symbol=item.get("displaySymbol") or item["symbol"],
                description=item.get("description") or "",
                type=item.get("type") or "",
            )
            for item in _expect_list(raw.get("result", []), "/search result")
            if item.get("symbol")
        ]

    @cached(ttl=TTL_SYMBOL_LIST)
    async def list_symbols(self, exchange: str) -> list[SymbolRecord]:
        # Large lists (e.g. US) redirect to a signed file on static2.finnhub.io, Finnhub's own CDN.
        raw = await self._get("/stock/symbol", {"exchange": exchange}, follow_redirects=True)
        return [
            SymbolRecord(
                symbol=item["symbol"],
                display_symbol=item.get("displaySymbol") or item["symbol"],
                description=item.get("description") or "",
                type=item.get("type") or "",
                currency=item.get("currency") or None,
                mic=item.get("mic") or None,
                figi=item.get("figi") or None,
            )
            for item in _expect_list(raw, "/stock/symbol")
            if item.get("symbol")
        ]

    @cached(ttl=TTL_SYMBOL_LIST)
    async def list_forex_symbols(self, exchange: str) -> list[ForexSymbol]:
        raw = await self._get("/forex/symbol", {"exchange": exchange})
        return [
            ForexSymbol(
                symbol=item["symbol"],
                display_symbol=item.get("displaySymbol") or item["symbol"],
                description=item.get("description") or "",
            )
            for item in _expect_list(raw, "/forex/symbol")
            if item.get("symbol")
        ]

    @cached(ttl=TTL_REFERENCE)
    async def get_company_profile(self, symbol: str) -> CompanyProfile:
        raw = _expect_dict(await self._get("/stock/profile2", {"symbol": symbol}), "/stock/profile2")
        if not raw.get("name"):
            raise NoDataError(self.name, f"no profile for {symbol}")
        market_cap = _dec(raw.get("marketCapitalization"))
        shares = _dec(raw.get("shareOutstanding"))
        return CompanyProfile(
            symbol=raw.get("ticker") or symbol,
            name=raw["name"],
            country=raw.get("country") or None,
            currency=raw.get("currency") or None,
            exchange=raw.get("exchange") or None,
            industry=raw.get("finnhubIndustry") or None,
            ipo_date=_date(raw.get("ipo")),
            logo_url=raw.get("logo") or None,
            website=raw.get("weburl") or None,
            # Finnhub reports market cap and shares outstanding in millions.
            market_cap=market_cap * MILLION if market_cap is not None else None,
            shares_outstanding=shares * MILLION if shares is not None else None,
        )

    @cached(ttl=TTL_REFERENCE)
    async def get_key_metrics(self, symbol: str) -> KeyMetrics:
        raw = _expect_dict(
            await self._get("/stock/metric", {"symbol": symbol, "metric": "all"}), "/stock/metric"
        )
        m = raw.get("metric") or {}
        if not m:
            raise NoDataError(self.name, f"no metrics for {symbol}")
        avg_10d = _dec(m.get("10DayAverageTradingVolume"))
        avg_3m = _dec(m.get("3MonthAverageTradingVolume"))
        return KeyMetrics(
            symbol=symbol,
            week52_high=_dec(m.get("52WeekHigh")),
            week52_high_date=_date(m.get("52WeekHighDate")),
            week52_low=_dec(m.get("52WeekLow")),
            week52_low_date=_date(m.get("52WeekLowDate")),
            pe_ttm=_dec(m.get("peTTM")),
            eps_ttm=_dec(m.get("epsTTM")),
            pb=_dec(m.get("pb")),
            ps_ttm=_dec(m.get("psTTM")),
            beta=_dec(m.get("beta")),
            dividend_yield_pct=_dec(m.get("dividendYieldIndicatedAnnual")),
            roe_ttm_pct=_dec(m.get("roeTTM")),
            net_margin_ttm_pct=_dec(m.get("netProfitMarginTTM")),
            revenue_growth_ttm_yoy_pct=_dec(m.get("revenueGrowthTTMYoy")),
            # Finnhub reports average volumes in millions of shares.
            avg_volume_10d=avg_10d * MILLION if avg_10d is not None else None,
            avg_volume_3m=avg_3m * MILLION if avg_3m is not None else None,
        )

    @cached(ttl=TTL_NEWS)
    async def get_company_news(self, symbol: str, start: date, end: date) -> list[NewsItem]:
        raw = await self._get(
            "/company-news", {"symbol": symbol, "from": start.isoformat(), "to": end.isoformat()}
        )
        return [_news(item) for item in _expect_list(raw, "/company-news") if item.get("headline")]

    @cached(ttl=TTL_NEWS)
    async def get_market_news(self, category: str = "general") -> list[NewsItem]:
        raw = await self._get("/news", {"category": category})
        return [_news(item) for item in _expect_list(raw, "/news") if item.get("headline")]

    @cached(ttl=TTL_CALENDAR)
    async def get_earnings_calendar(self, start: date, end: date) -> list[EarningsEvent]:
        raw = _expect_dict(
            await self._get("/calendar/earnings", {"from": start.isoformat(), "to": end.isoformat()}),
            "/calendar/earnings",
        )
        events = []
        for item in _expect_list(raw.get("earningsCalendar", []), "/calendar/earnings"):
            event_date = _date(item.get("date"))
            if not item.get("symbol") or event_date is None:
                continue
            events.append(
                EarningsEvent(
                    symbol=item["symbol"],
                    date=event_date,
                    session=_EARNINGS_HOUR.get(item.get("hour") or "", EarningsSession.UNKNOWN),
                    quarter=item.get("quarter"),
                    year=item.get("year"),
                    eps_estimate=_dec(item.get("epsEstimate")),
                    eps_actual=_dec(item.get("epsActual")),
                    revenue_estimate=_dec(item.get("revenueEstimate")),
                    revenue_actual=_dec(item.get("revenueActual")),
                )
            )
        return events

    @cached(ttl=TTL_CALENDAR)
    async def get_ipo_calendar(self, start: date, end: date) -> list[IpoEvent]:
        raw = _expect_dict(
            await self._get("/calendar/ipo", {"from": start.isoformat(), "to": end.isoformat()}),
            "/calendar/ipo",
        )
        events = []
        for item in _expect_list(raw.get("ipoCalendar", []), "/calendar/ipo"):
            event_date = _date(item.get("date"))
            if not item.get("name") or event_date is None:
                continue
            events.append(
                IpoEvent(
                    symbol=item.get("symbol") or None,
                    name=item["name"],
                    date=event_date,
                    exchange=item.get("exchange") or None,
                    status=item.get("status") or None,
                    price_range=str(item["price"]) if item.get("price") else None,
                    shares=item.get("numberOfShares"),
                    total_value=_dec(item.get("totalSharesValue")),
                )
            )
        return events

    @cached(ttl=TTL_MARKET_STATUS)
    async def get_market_status(self, exchange: str) -> MarketStatus:
        raw = _expect_dict(
            await self._get("/stock/market-status", {"exchange": exchange}), "/stock/market-status"
        )
        is_open = bool(raw.get("isOpen"))
        return MarketStatus(
            exchange=raw.get("exchange") or exchange,
            is_open=is_open,
            session=_SESSION.get(raw.get("session") or "", MarketSession.CLOSED),
            holiday=raw.get("holiday") or None,
            timezone=raw.get("timezone") or None,
            timestamp=_ts(raw.get("t")),
        )

    @cached(ttl=TTL_REFERENCE)
    async def get_market_holidays(self, exchange: str) -> list[MarketHoliday]:
        raw = _expect_dict(
            await self._get("/stock/market-holiday", {"exchange": exchange}), "/stock/market-holiday"
        )
        holidays = []
        for item in _expect_list(raw.get("data", []), "/stock/market-holiday"):
            holiday_date = _date(item.get("atDate"))
            if holiday_date is None:
                continue
            holidays.append(
                MarketHoliday(
                    name=item.get("eventName") or "Holiday",
                    date=holiday_date,
                    trading_hours=item.get("tradingHour") or None,
                )
            )
        return holidays


def _news(item: dict[str, Any]) -> NewsItem:
    related = item.get("related") or ""
    published = _ts(item.get("datetime"))
    return NewsItem(
        id=str(item.get("id") or item.get("url") or item["headline"]),
        headline=item["headline"],
        summary=item.get("summary") or "",
        source=item.get("source") or "",
        url=item.get("url") or "",
        image_url=item.get("image") or None,
        published_at=published or datetime.now(UTC),
        category=item.get("category") or None,
        related_symbols=[s for s in related.split(",") if s],
    )


def _expect_dict(payload: Any, where: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ProviderError(FinnhubProvider.name, f"unexpected response shape from {where}")
    return payload


def _expect_list(payload: Any, where: str) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise ProviderError(FinnhubProvider.name, f"unexpected response shape from {where}")
    return [item for item in payload if isinstance(item, dict)]


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        # str() first so floats like 0.1 don't carry binary noise into Decimal.
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _require_dec(value: Any, field: str) -> Decimal:
    result = _dec(value)
    if result is None:
        raise ProviderError(FinnhubProvider.name, f"missing numeric field {field}")
    return result


def _ts(value: Any) -> datetime | None:
    if not isinstance(value, int | float) or value <= 0:
        return None
    return datetime.fromtimestamp(value, tz=UTC)


def _date(value: Any) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None

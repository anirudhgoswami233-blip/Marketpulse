"""Twelve Data adapter (approved fallback): price history and forex rates, which Finnhub's free tier blocks.

The free plan allows 8 calls/min and 800/day. Our limiter targets 7/min and 750/day, and daily bars are
persisted to `price_bars` so history is fetched once and then only topped up.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.core.cache import CacheBackend, Fetched, cached
from app.core.errors import NoDataError, ProviderError, ProviderUnavailable, RateLimitExceeded
from app.core.ratelimit import RateLimiter
from app.providers.base import Bar, Bars, ForexRate, Interval, MarketDataProvider, Quote
from app.providers.http import ProviderTransport

BASE_URL = "https://api.twelvedata.com"

TTL_DAILY_BARS = 6 * 3600
TTL_INTRADAY_BARS = 5 * 60
TTL_FOREX_RATE = 60
# Quotes cost one credit per symbol against 8/min and 800/day, so they're cached longer than Finnhub's (60s)
# and the UI labels them as delayed.
TTL_QUOTE = 5 * 60

# Our symbol directory uses Finnhub-style forex symbols (OANDA:EUR_USD); Twelve Data wants EUR/USD.
_FOREX_SYMBOL = re.compile(r"^[A-Z]+:([A-Z]{3})_([A-Z]{3})$")


def build_client(api_key: str, timeout_s: float = 20.0) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=BASE_URL, headers={"Authorization": f"apikey {api_key}"}, timeout=timeout_s
    )


def to_vendor_symbol(symbol: str) -> str:
    match = _FOREX_SYMBOL.match(symbol)
    return f"{match.group(1)}/{match.group(2)}" if match else symbol


class TwelveDataProvider(MarketDataProvider):
    name = "twelvedata"

    def __init__(self, client: httpx.AsyncClient, limiter: RateLimiter, cache: CacheBackend) -> None:
        self.cache = cache
        self._http = ProviderTransport(self.name, client, limiter)

    async def _get(self, path: str, params: dict[str, str | int]) -> dict[str, Any]:
        payload = await self._http.get_json(path, params, body_error_statuses=(400, 401, 403, 404, 429))
        if not isinstance(payload, dict):
            raise ProviderError(self.name, f"unexpected response shape from {path}")
        # Twelve Data reports errors in the body, sometimes with HTTP 200.
        if payload.get("status") == "error":
            code = payload.get("code")
            message = str(payload.get("message", "unknown error"))[:200]
            # Symbols outside our plan (e.g. NSE on free) return 404 "available starting with ...".
            if "available starting with" in message.lower() or "upgrad" in message.lower():
                raise ProviderUnavailable(self.name, f"{path}: not available on our plan")
            if code == 429:
                raise RateLimitExceeded(self.name, f"{path}: {message}")
            if code in (401, 403):
                raise ProviderUnavailable(self.name, f"{path}: {message}")
            if code in (400, 404):
                raise NoDataError(self.name, f"{path}: {message}")
            raise ProviderError(self.name, f"{path}: {message}")
        return payload

    async def get_bars(self, symbol: str, interval: Interval, outputsize: int) -> Fetched[Bars]:
        # Intraday data changes far faster than daily bars, so it gets a much shorter TTL.
        if interval in (Interval.DAY_1, Interval.WEEK_1):
            return await self._get_daily_bars(symbol, interval, outputsize)
        return await self._get_intraday_bars(symbol, interval, outputsize)

    @cached(ttl=TTL_DAILY_BARS)
    async def _get_daily_bars(self, symbol: str, interval: Interval, outputsize: int) -> Bars:
        return await self._fetch_bars(symbol, interval, outputsize)

    @cached(ttl=TTL_INTRADAY_BARS)
    async def _get_intraday_bars(self, symbol: str, interval: Interval, outputsize: int) -> Bars:
        return await self._fetch_bars(symbol, interval, outputsize)

    async def _fetch_bars(self, symbol: str, interval: Interval, outputsize: int) -> Bars:
        raw = await self._get(
            "/time_series",
            {
                "symbol": to_vendor_symbol(symbol),
                "interval": interval.value,
                "outputsize": max(1, min(outputsize, 5000)),
                "timezone": "UTC",
                "order": "asc",
            },
        )
        meta = raw.get("meta") or {}
        values = raw.get("values")
        if not isinstance(values, list) or not values:
            raise NoDataError(self.name, f"no bars for {symbol}")
        bars = [bar for bar in (_bar(v) for v in values if isinstance(v, dict)) if bar is not None]
        bars.sort(key=lambda b: b.timestamp)
        return Bars(
            symbol=symbol,
            interval=interval,
            currency=meta.get("currency") or None,
            exchange_timezone=meta.get("exchange_timezone") or None,
            bars=bars,
        )

    @cached(ttl=TTL_QUOTE)
    async def get_quote(self, symbol: str) -> Quote:
        raw = await self._get("/quote", {"symbol": to_vendor_symbol(symbol)})
        price = _dec(raw.get("close"))
        if price is None:
            raise NoDataError(self.name, f"no quote for {symbol}")
        last = raw.get("last_quote_at") or raw.get("timestamp")
        return Quote(
            symbol=symbol,
            price=price,
            change=_dec(raw.get("change")),
            change_pct=_dec(raw.get("percent_change")),
            open=_dec(raw.get("open")),
            high=_dec(raw.get("high")),
            low=_dec(raw.get("low")),
            prev_close=_dec(raw.get("previous_close")),
            timestamp=datetime.fromtimestamp(last, tz=UTC) if isinstance(last, int | float) else None,
        )

    @cached(ttl=TTL_FOREX_RATE)
    async def get_forex_rate(self, base: str, quote: str) -> ForexRate:
        raw = await self._get("/exchange_rate", {"symbol": f"{base.upper()}/{quote.upper()}"})
        rate = _dec(raw.get("rate"))
        if rate is None:
            raise NoDataError(self.name, f"no rate for {base}/{quote}")
        timestamp = raw.get("timestamp")
        return ForexRate(
            base=base.upper(),
            quote=quote.upper(),
            rate=rate,
            timestamp=datetime.fromtimestamp(timestamp, tz=UTC)
            if isinstance(timestamp, int | float)
            else None,
        )


def _bar(value: dict[str, Any]) -> Bar | None:
    timestamp = _parse_datetime(value.get("datetime"))
    o, h, low, c = (_dec(value.get(k)) for k in ("open", "high", "low", "close"))
    if timestamp is None or o is None or h is None or low is None or c is None:
        return None
    volume = _dec(value.get("volume"))
    return Bar(timestamp=timestamp, open=o, high=h, low=low, close=c, volume=int(volume) if volume else None)


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        if len(value) == 10:
            return datetime.combine(date.fromisoformat(value), time(0), tzinfo=UTC)
        return datetime.fromisoformat(value).replace(tzinfo=UTC)
    except ValueError:
        return None


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None

from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
import respx

from app.core.cache import MemoryCache
from app.core.errors import NoDataError, ProviderUnavailable, RateLimitExceeded
from app.core.ratelimit import MemoryRateLimiter
from app.providers.base import Interval
from app.providers.fallback.twelvedata import BASE_URL, TwelveDataProvider, build_client, to_vendor_symbol
from tests.conftest import FAKE_TWELVEDATA_KEY

SERIES = {
    "meta": {
        "symbol": "AAPL",
        "interval": "1day",
        "currency": "USD",
        "exchange_timezone": "America/New_York",
    },
    "values": [
        {
            "datetime": "2026-10-16",
            "open": "250.1",
            "high": "253",
            "low": "249.5",
            "close": "252.29",
            "volume": "41234567",
        },
        {
            "datetime": "2026-10-15",
            "open": "248",
            "high": "251",
            "low": "247.2",
            "close": "250.0",
            "volume": "38000000",
        },
    ],
    "status": "ok",
}


@pytest.fixture
def provider(
    cache: MemoryCache, limiter: MemoryRateLimiter, http_client_factory: list[httpx.AsyncClient]
) -> TwelveDataProvider:
    client = build_client(FAKE_TWELVEDATA_KEY)
    http_client_factory.append(client)
    return TwelveDataProvider(client, limiter, cache)


async def test_daily_bars_are_sorted_and_decimal(
    provider: TwelveDataProvider, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get(f"{BASE_URL}/time_series").respond(json=SERIES)

    result = await provider.get_bars("AAPL", Interval.DAY_1, 2)

    bars = result.data.bars
    assert [b.timestamp for b in bars] == [
        datetime(2026, 10, 15, tzinfo=UTC),
        datetime(2026, 10, 16, tzinfo=UTC),
    ]
    assert bars[-1].close == Decimal("252.29")
    assert bars[-1].volume == 41234567
    assert result.data.currency == "USD"
    request = route.calls.last.request
    assert request.headers["Authorization"] == f"apikey {FAKE_TWELVEDATA_KEY}"
    assert FAKE_TWELVEDATA_KEY not in str(request.url)
    assert request.url.params["timezone"] == "UTC"


async def test_intraday_timestamps_parse_as_utc(
    provider: TwelveDataProvider, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get(f"{BASE_URL}/time_series").respond(
        json={
            "meta": {},
            "status": "ok",
            "values": [
                {"datetime": "2026-10-16 14:35:00", "open": "1", "high": "2", "low": "0.5", "close": "1.5"}
            ],
        }
    )
    bars = (await provider.get_bars("AAPL", Interval.MIN_5, 1)).data.bars
    assert bars[0].timestamp == datetime(2026, 10, 16, 14, 35, tzinfo=UTC)
    assert bars[0].volume is None


def test_forex_symbols_are_translated() -> None:
    assert to_vendor_symbol("OANDA:USD_INR") == "USD/INR"
    assert to_vendor_symbol("AAPL") == "AAPL"


@pytest.mark.parametrize(
    ("code", "error"),
    [(429, RateLimitExceeded), (401, ProviderUnavailable), (403, ProviderUnavailable), (400, NoDataError)],
)
async def test_errors_in_200_body_are_mapped(
    provider: TwelveDataProvider, respx_mock: respx.MockRouter, code: int, error: type[Exception]
) -> None:
    respx_mock.get(f"{BASE_URL}/time_series").respond(
        json={"code": code, "message": "something went wrong", "status": "error"}
    )
    with pytest.raises(error):
        await provider.get_bars("RELIANCE", Interval.DAY_1, 30)


async def test_plan_gated_symbol_is_unavailable_not_missing(
    provider: TwelveDataProvider, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get(f"{BASE_URL}/time_series").respond(
        404,
        json={
            "code": 404,
            "message": "This symbol is available starting with the Grow or Venture plan.",
            "status": "error",
        },
    )
    with pytest.raises(ProviderUnavailable, match="not available on our plan"):
        await provider.get_bars("RELIANCE:NSE", Interval.DAY_1, 5)


async def test_http_404_for_unknown_symbol_is_no_data(
    provider: TwelveDataProvider, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get(f"{BASE_URL}/time_series").respond(
        404, json={"code": 404, "message": "symbol not found", "status": "error"}
    )
    with pytest.raises(NoDataError):
        await provider.get_bars("ZZZZ", Interval.DAY_1, 5)


async def test_empty_values_is_no_data(provider: TwelveDataProvider, respx_mock: respx.MockRouter) -> None:
    respx_mock.get(f"{BASE_URL}/time_series").respond(json={"meta": {}, "values": [], "status": "ok"})
    with pytest.raises(NoDataError):
        await provider.get_bars("AAPL", Interval.DAY_1, 30)


async def test_forex_rate_mapping(provider: TwelveDataProvider, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(f"{BASE_URL}/exchange_rate").respond(
        json={"symbol": "USD/INR", "rate": 84.1234, "timestamp": 1792540800}
    )
    rate = (await provider.get_forex_rate("usd", "inr")).data
    assert rate.rate == Decimal("84.1234")
    assert (rate.base, rate.quote) == ("USD", "INR")
    assert route.calls.last.request.url.params["symbol"] == "USD/INR"

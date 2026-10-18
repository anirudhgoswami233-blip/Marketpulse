from datetime import UTC, date, datetime
from decimal import Decimal

import httpx
import pytest
import respx

from app.core.cache import MemoryCache
from app.core.errors import NoDataError, ProviderError, ProviderUnavailable, RateLimitExceeded
from app.core.ratelimit import MemoryRateLimiter
from app.providers.base import EarningsSession, MarketSession
from app.providers.finnhub import BASE_URL, FinnhubProvider, build_client
from tests.conftest import FAKE_FINNHUB_KEY, FakeClock

QUOTE = {
    "c": 252.29,
    "d": 1.21,
    "dp": 0.4819,
    "h": 253.0,
    "l": 249.5,
    "o": 250.1,
    "pc": 251.08,
    "t": 1792540800,
}


@pytest.fixture
def provider(
    cache: MemoryCache, limiter: MemoryRateLimiter, http_client_factory: list[httpx.AsyncClient]
) -> FinnhubProvider:
    client = build_client(FAKE_FINNHUB_KEY)
    http_client_factory.append(client)
    return FinnhubProvider(client, limiter, cache)


async def test_quote_maps_fields_to_decimal_and_sends_key_in_header(
    provider: FinnhubProvider, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get(f"{BASE_URL}/quote", params={"symbol": "AAPL"}).respond(json=QUOTE)

    result = await provider.get_quote("AAPL")

    quote = result.data
    assert quote.price == Decimal("252.29")
    assert quote.change_pct == Decimal("0.4819")
    assert quote.prev_close == Decimal("251.08")
    assert quote.timestamp == datetime.fromtimestamp(1792540800, tz=UTC)
    assert result.source == "finnhub" and result.stale is False
    request = route.calls.last.request
    assert request.headers["X-Finnhub-Token"] == FAKE_FINNHUB_KEY
    assert FAKE_FINNHUB_KEY not in str(request.url)


async def test_quote_is_cached(provider: FinnhubProvider, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(f"{BASE_URL}/quote").respond(json=QUOTE)
    await provider.get_quote("AAPL")
    await provider.get_quote("AAPL")
    assert route.call_count == 1


async def test_zero_quote_means_unknown_symbol(
    provider: FinnhubProvider, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get(f"{BASE_URL}/quote").respond(
        json={"c": 0, "d": None, "dp": None, "h": 0, "l": 0, "o": 0, "pc": 0, "t": 0}
    )
    with pytest.raises(NoDataError):
        await provider.get_quote("NOPE")


async def test_429_backs_off_and_retries_once(
    provider: FinnhubProvider, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get(f"{BASE_URL}/quote").mock(
        side_effect=[httpx.Response(429, headers={"Retry-After": "0"}), httpx.Response(200, json=QUOTE)]
    )
    result = await provider.get_quote("AAPL")
    assert result.data.price == Decimal("252.29")
    assert route.call_count == 2


async def test_repeated_429_raises_rate_limit(
    provider: FinnhubProvider, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get(f"{BASE_URL}/quote").respond(429, headers={"Retry-After": "0"})
    with pytest.raises(RateLimitExceeded):
        await provider.get_quote("AAPL")
    assert route.call_count == 2  # one retry, no more


async def test_repeated_429_serves_stale_quote_when_cached(
    limiter: MemoryRateLimiter,
    respx_mock: respx.MockRouter,
    http_client_factory: list[httpx.AsyncClient],
    clock: FakeClock,
) -> None:
    client = build_client(FAKE_FINNHUB_KEY)
    http_client_factory.append(client)
    provider = FinnhubProvider(client, limiter, MemoryCache(clock=clock))
    respx_mock.get(f"{BASE_URL}/quote").mock(
        side_effect=[
            httpx.Response(200, json=QUOTE),
            httpx.Response(429, headers={"Retry-After": "0"}),
            httpx.Response(429, headers={"Retry-After": "0"}),
        ]
    )
    fresh = await provider.get_quote("AAPL")
    clock.now += 61

    stale = await provider.get_quote("AAPL")

    assert stale.stale is True
    assert stale.as_of == fresh.as_of
    assert stale.data.price == Decimal("252.29")


async def test_403_raises_provider_unavailable(
    provider: FinnhubProvider, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get(f"{BASE_URL}/quote").respond(
        403, json={"error": "You don't have access to this resource."}
    )
    with pytest.raises(ProviderUnavailable):
        await provider.get_quote("RELIANCE.NS")


async def test_error_in_200_body_is_mapped(provider: FinnhubProvider, respx_mock: respx.MockRouter) -> None:
    respx_mock.get(f"{BASE_URL}/quote").respond(
        json={"error": "Market data subscription required for CFD indices."}
    )
    with pytest.raises(ProviderUnavailable, match="subscription"):
        await provider.get_quote("^GSPC")


async def test_malformed_json_raises_provider_error(
    provider: FinnhubProvider, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get(f"{BASE_URL}/quote").respond(200, content=b"<html>oops</html>")
    with pytest.raises(ProviderError, match="malformed"):
        await provider.get_quote("AAPL")


async def test_unexpected_shape_raises_provider_error(
    provider: FinnhubProvider, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get(f"{BASE_URL}/company-news").respond(json={"not": "a list"})
    with pytest.raises(ProviderError, match="unexpected response shape"):
        await provider.get_company_news("AAPL", date(2026, 10, 1), date(2026, 10, 7))


async def test_network_error_raises_provider_error_without_leaking_key(
    provider: FinnhubProvider, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get(f"{BASE_URL}/quote").mock(side_effect=httpx.ConnectError("connection refused"))
    with pytest.raises(ProviderError) as exc_info:
        await provider.get_quote("AAPL")
    assert FAKE_FINNHUB_KEY not in str(exc_info.value)
    assert "ConnectError on /quote" in str(exc_info.value)


async def test_symbol_list_follows_redirect_to_finnhub_cdn(
    provider: FinnhubProvider, respx_mock: respx.MockRouter
) -> None:
    cdn_url = "https://static2.finnhub.io/file/privatedatany2/exchange/USf.json?sig=abc"
    respx_mock.get(f"{BASE_URL}/stock/symbol").respond(302, headers={"Location": cdn_url})
    respx_mock.get(cdn_url).respond(
        json=[
            {
                "symbol": "AAPL",
                "displaySymbol": "AAPL",
                "description": "APPLE INC",
                "type": "Common Stock",
                "currency": "USD",
                "mic": "XNAS",
                "figi": "BBG000B9XRY4",
            },
            {"description": "missing symbol is skipped"},
        ]
    )
    result = await provider.list_symbols("US")
    assert [s.symbol for s in result.data] == ["AAPL"]
    assert result.data[0].mic == "XNAS"


async def test_profile_converts_millions(provider: FinnhubProvider, respx_mock: respx.MockRouter) -> None:
    respx_mock.get(f"{BASE_URL}/stock/profile2").respond(
        json={
            "ticker": "AAPL",
            "name": "Apple Inc",
            "country": "US",
            "currency": "USD",
            "exchange": "NASDAQ NMS",
            "finnhubIndustry": "Technology",
            "ipo": "1980-12-12",
            "logo": "https://x/logo.png",
            "marketCapitalization": 3750000.5,
            "shareOutstanding": 14840.39,
            "weburl": "https://apple.com",
        }
    )
    profile = (await provider.get_company_profile("AAPL")).data
    assert profile.market_cap == Decimal("3750000500000.0")
    assert profile.shares_outstanding == Decimal("14840390000.00")
    assert profile.ipo_date == date(1980, 12, 12)
    assert profile.industry == "Technology"


async def test_empty_profile_is_no_data(provider: FinnhubProvider, respx_mock: respx.MockRouter) -> None:
    respx_mock.get(f"{BASE_URL}/stock/profile2").respond(json={})
    with pytest.raises(NoDataError):
        await provider.get_company_profile("ZZZZ")


async def test_key_metrics_mapping(provider: FinnhubProvider, respx_mock: respx.MockRouter) -> None:
    respx_mock.get(f"{BASE_URL}/stock/metric").respond(
        json={
            "symbol": "AAPL",
            "metricType": "all",
            "series": {},
            "metric": {
                "52WeekHigh": 260.1,
                "52WeekHighDate": "2026-09-30",
                "52WeekLow": 169.2,
                "peTTM": 38.2,
                "beta": 1.2,
                "10DayAverageTradingVolume": 55.5,
            },
        }
    )
    metrics = (await provider.get_key_metrics("AAPL")).data
    assert metrics.week52_high == Decimal("260.1")
    assert metrics.week52_high_date == date(2026, 9, 30)
    assert metrics.avg_volume_10d == Decimal("55500000.0")
    assert metrics.eps_ttm is None


async def test_news_mapping(provider: FinnhubProvider, respx_mock: respx.MockRouter) -> None:
    respx_mock.get(f"{BASE_URL}/news").respond(
        json=[
            {
                "category": "top news",
                "datetime": 1792540800,
                "headline": "Stocks rally",
                "id": 42,
                "image": "",
                "related": "AAPL,MSFT",
                "source": "Reuters",
                "summary": "s",
                "url": "https://n/1",
            }
        ]
    )
    item = (await provider.get_market_news()).data[0]
    assert item.id == "42"
    assert item.related_symbols == ["AAPL", "MSFT"]
    assert item.image_url is None
    assert item.published_at.tzinfo is not None


async def test_earnings_calendar_mapping(provider: FinnhubProvider, respx_mock: respx.MockRouter) -> None:
    respx_mock.get(f"{BASE_URL}/calendar/earnings").respond(
        json={
            "earningsCalendar": [
                {
                    "date": "2026-10-28",
                    "epsActual": None,
                    "epsEstimate": 1.6,
                    "hour": "amc",
                    "quarter": 4,
                    "revenueActual": None,
                    "revenueEstimate": 101000000000,
                    "symbol": "AAPL",
                    "year": 2026,
                },
                {"date": "2026-10-29", "hour": "", "symbol": "XYZ"},
            ]
        }
    )
    events = (await provider.get_earnings_calendar(date(2026, 10, 19), date(2026, 11, 2))).data
    assert events[0].session is EarningsSession.AFTER_CLOSE
    assert events[0].eps_estimate == Decimal("1.6")
    assert events[1].session is EarningsSession.UNKNOWN


async def test_market_status_mapping(provider: FinnhubProvider, respx_mock: respx.MockRouter) -> None:
    respx_mock.get(f"{BASE_URL}/stock/market-status").respond(
        json={
            "exchange": "US",
            "holiday": None,
            "isOpen": False,
            "session": None,
            "t": 1792540800,
            "timezone": "America/New_York",
        }
    )
    status = (await provider.get_market_status("US")).data
    assert status.is_open is False
    assert status.session is MarketSession.CLOSED
    assert status.timezone == "America/New_York"


async def test_unsupported_capability_raises(provider: FinnhubProvider) -> None:
    from app.providers.base import Interval

    with pytest.raises(ProviderUnavailable):
        await provider.get_bars("AAPL", Interval.DAY_1, 365)

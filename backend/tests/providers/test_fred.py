from datetime import date
from decimal import Decimal

import httpx
import pytest
import respx

from app.core.cache import MemoryCache
from app.core.errors import NoDataError, ProviderError
from app.core.ratelimit import MemoryRateLimiter
from app.providers.fred import BASE_URL, FredProvider, build_client
from tests.conftest import FAKE_FRED_KEY

SERIES_INFO = {
    "seriess": [
        {
            "id": "FEDFUNDS",
            "title": "Federal Funds Effective Rate",
            "units_short": "%",
            "frequency_short": "M",
            "last_updated": "2026-10-01 15:16:02-05",
        }
    ]
}


@pytest.fixture
def provider(
    cache: MemoryCache, limiter: MemoryRateLimiter, http_client_factory: list[httpx.AsyncClient]
) -> FredProvider:
    client = build_client()
    http_client_factory.append(client)
    return FredProvider(client, limiter, cache, FAKE_FRED_KEY)


async def test_series_mapping_skips_missing_values(
    provider: FredProvider, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get(f"{BASE_URL}/series").respond(json=SERIES_INFO)
    obs_route = respx_mock.get(f"{BASE_URL}/series/observations").respond(
        json={
            "observations": [
                {"date": "2026-08-01", "value": "4.33"},
                {"date": "2026-09-01", "value": "."},
                {"date": "2026-10-01", "value": "4.08"},
            ]
        }
    )

    series = (await provider.get_series("FEDFUNDS", date(2026, 1, 1))).data

    assert series.title == "Federal Funds Effective Rate"
    assert series.units == "%"
    assert [o.value for o in series.observations] == [Decimal("4.33"), Decimal("4.08")]
    assert series.last_updated is not None
    params = obs_route.calls.last.request.url.params
    assert params["api_key"] == FAKE_FRED_KEY and params["file_type"] == "json"


async def test_unknown_series_is_no_data(provider: FredProvider, respx_mock: respx.MockRouter) -> None:
    respx_mock.get(f"{BASE_URL}/series").respond(json={"seriess": []})
    with pytest.raises(NoDataError):
        await provider.get_series("NOPE", date(2026, 1, 1))


async def test_server_error_message_never_contains_key(
    provider: FredProvider, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get(f"{BASE_URL}/series").respond(500, text="internal error")
    with pytest.raises(ProviderError) as exc_info:
        await provider.get_series("FEDFUNDS", date(2026, 1, 1))
    assert FAKE_FRED_KEY not in str(exc_info.value)
    assert str(exc_info.value) == "fred: HTTP 500 on /series"

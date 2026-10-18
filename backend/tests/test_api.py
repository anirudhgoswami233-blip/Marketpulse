import asyncio
import dataclasses
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

import app.models  # noqa: F401
from app.api import stream as stream_api
from app.container import Container
from app.core.config import Settings
from app.core.errors import ProviderUnavailable
from app.db import Base
from app.main import create_app
from app.providers.base import SymbolRecord
from app.services import symbol_directory
from app.ws.hub import Trade
from tests.conftest import FAKE_FINNHUB_KEY
from tests.fakes import FakeProvider, make_quote


def make_settings(**overrides: Any) -> Settings:
    return Settings(
        _env_file=None,
        database_url="sqlite+aiosqlite:///:memory:",
        enable_background_jobs=False,
        enable_streaming=False,
        **overrides,
    )


async def _prepare(container: Container, provider: FakeProvider) -> None:
    async with container.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with container.session_factory() as session:
        await symbol_directory.upsert_exchanges(session, symbol_directory.load_exchange_rows())
        await symbol_directory.upsert_symbols(
            session,
            "US",
            [
                SymbolRecord(
                    symbol="AAPL",
                    display_symbol="AAPL",
                    description="APPLE INC",
                    type="Common Stock",
                    currency="USD",
                    mic="XNAS",
                    figi=None,
                )
            ],
        )
        await symbol_directory.upsert_symbols(
            session,
            "L",
            [
                SymbolRecord(
                    symbol="VOD",
                    display_symbol="VOD",
                    description="VODAFONE",
                    type="Common Stock",
                    currency="GBP",
                    mic="XLON",
                    figi=None,
                )
            ],
        )
        await session.commit()
    container.providers = dataclasses.replace(
        container.providers,
        quotes=provider,
        reference=provider,
        news=provider,
        market_status=provider,
        history=provider,
    )


@pytest.fixture
def provider() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def client(provider: FakeProvider) -> Iterator[TestClient]:
    with TestClient(create_app(make_settings())) as test_client:
        container: Container = test_client.app.state.container  # type: ignore[attr-defined]
        assert test_client.portal is not None
        test_client.portal.call(_prepare, container, provider)
        yield test_client


def test_health(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_system_status_reports_configuration_without_secrets() -> None:
    settings = make_settings(finnhub_api_key=SecretStr(FAKE_FINNHUB_KEY))
    with TestClient(create_app(settings)) as test_client:
        response = test_client.get("/api/v1/system/status")

    assert response.status_code == 200
    body = response.json()
    assert FAKE_FINNHUB_KEY not in response.text
    assert body["cache_backend"] == "memory"
    assert {p["name"]: p["configured"] for p in body["providers"]} == {
        "finnhub": True,
        "twelvedata": False,
        "fred": False,
    }
    finnhub = next(limiter for limiter in body["limiters"] if limiter["name"] == "finnhub")
    assert finnhub["limit_per_window"] == 50


def test_search_and_symbol_lookup(client: TestClient) -> None:
    results = client.get("/api/v1/search", params={"q": "app"}).json()["results"]
    assert results[0]["symbol"] == "AAPL"
    assert results[0]["price_available"] is True

    vod = client.get("/api/v1/stocks/VOD").json()
    assert vod["exchange"] == "L" and vod["price_available"] is False and vod["streamable"] is False


def test_unknown_symbol_is_404_with_code(client: TestClient) -> None:
    response = client.get("/api/v1/stocks/NOPE/quote")
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_invalid_symbol_is_rejected(client: TestClient) -> None:
    assert client.get("/api/v1/stocks/AA PL").status_code == 422


def test_quote_envelope(client: TestClient, provider: FakeProvider) -> None:
    provider.quotes["AAPL"] = make_quote("AAPL", "252.29", "0.48")
    body = client.get("/api/v1/stocks/AAPL/quote").json()
    assert Decimal(body["data"]["price"]) == Decimal("252.29")
    assert body["data"]["currency"] == "USD"
    assert body["source"] == "fake" and body["stale"] is False and body["as_of"]


def test_unavailable_data_returns_friendly_503(client: TestClient) -> None:
    response = client.get("/api/v1/stocks/AAPL/profile")
    assert response.status_code == 503
    assert response.json()["code"] == "unavailable"
    assert "fake" not in response.json()["detail"]


def test_overview_before_first_refresh(client: TestClient) -> None:
    body = client.get("/api/v1/markets/overview").json()
    assert body["as_of"] is None
    assert body["pending_symbols"] > 0
    assert {r["region"] for r in body["regions"]} >= {"Americas", "Europe", "India", "Asia-Pacific"}


def test_chart_range_validation(client: TestClient) -> None:
    assert client.get("/api/v1/stocks/AAPL/chart", params={"range": "2Y"}).status_code == 422


def test_stream_rejects_bad_requests(client: TestClient) -> None:
    assert client.get("/api/v1/stream", params={"symbols": ""}).status_code == 422
    too_many = ",".join(f"S{i}" for i in range(31))
    assert client.get("/api/v1/stream", params={"symbols": too_many}).status_code == 422


class FakeRequest:
    def __init__(self, disconnect_after: int) -> None:
        self.checks = 0
        self.disconnect_after = disconnect_after

    async def is_disconnected(self) -> bool:
        self.checks += 1
        return self.checks > self.disconnect_after


class FakeStream:
    def __init__(self) -> None:
        self.refs: dict[str, int] = {}

    async def acquire(self, symbol: str) -> bool:
        self.refs[symbol] = self.refs.get(symbol, 0) + 1
        return True

    async def release(self, symbol: str) -> None:
        self.refs[symbol] -= 1


async def test_sse_events_subscribe_stream_and_release() -> None:
    from app.ws.hub import PriceHub

    hub = PriceHub()
    hub.publish(
        Trade(symbol="AAPL", price=Decimal("252.5"), timestamp=datetime(2026, 10, 19, 14, tzinfo=UTC))
    )
    fake_stream = FakeStream()
    container = Container.__new__(Container)
    container.hub = hub
    container.stream = fake_stream  # type: ignore[assignment]

    events = stream_api._events(FakeRequest(1), container, ["AAPL", "VOD"], {"AAPL"})  # type: ignore[arg-type]
    chunks = [chunk async for chunk in events]

    ready = json.loads(chunks[0].split("data: ", 1)[1])
    assert ready == {"live": ["AAPL"], "unavailable": ["VOD"], "streaming_enabled": True}
    assert chunks[1].startswith("event: price")
    assert json.loads(chunks[1].split("data: ", 1)[1])["price"] == "252.5"
    assert fake_stream.refs == {"AAPL": 0}  # released on disconnect
    await asyncio.sleep(0)


def test_provider_unavailable_class_is_importable() -> None:
    # Guards the error mapping used by the UI ("unavailable" means not on our data plan).
    assert issubclass(ProviderUnavailable, Exception)

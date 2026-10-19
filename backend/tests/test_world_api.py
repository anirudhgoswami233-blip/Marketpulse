import dataclasses
import time as clock
from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.container import Container
from app.main import create_app
from app.providers.base import EarningsEvent, EarningsSession, IpoEvent
from tests.api_helpers import file_db, make_settings, prepare
from tests.fakes import FakeMacro, FakeProvider, make_quote
from tests.test_auth_and_portfolio_api import register


@pytest.fixture
def provider() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def forex() -> FakeProvider:
    fx = FakeProvider()
    fx.name = "fake-fx"
    fx.as_of = datetime.now(UTC)  # the API judges board freshness against the real clock
    for pair, price in {
        "EUR/USD": "1.10",
        "USD/INR": "80",
        "XAU/USD": "4000",
        "OANDA:XAU_USD": "4000",
    }.items():
        fx.quotes[pair] = make_quote(pair, price, prev_close=price)
    return fx


@pytest.fixture
def container_and_client(
    provider: FakeProvider, forex: FakeProvider, tmp_path: Path
) -> Iterator[tuple[Container, TestClient]]:
    with TestClient(create_app(make_settings(database_url=file_db(tmp_path)))) as client:
        container: Container = client.app.state.container  # type: ignore[attr-defined]
        assert client.portal is not None
        client.portal.call(prepare, container, provider)
        container.providers = dataclasses.replace(container.providers, forex_quotes=forex, forex_rates=forex)
        yield container, client


@pytest.fixture
def client(container_and_client: tuple[Container, TestClient]) -> TestClient:
    return container_and_client[1]


def test_metals_are_priced_by_the_forex_provider_but_not_tradable(client: TestClient) -> None:
    info = client.get("/api/v1/stocks/OANDA:XAU_USD").json()
    assert info["price_available"] and not info["tradable"] and not info["streamable"]
    assert (
        info["quote_delay_min"] == 5
        and "forex and metals can be watched but not traded" in info["trade_note"]
    )
    quote = client.get("/api/v1/stocks/OANDA:XAU_USD/quote").json()
    assert quote["source"] == "fake-fx" and Decimal(quote["data"]["price"]) == Decimal("4000")

    headers = register(client)
    order = client.post(
        "/api/v1/portfolio/orders",
        headers=headers,
        json={"symbol": "OANDA:XAU_USD", "side": "buy", "quantity": "1"},
    )
    assert order.status_code == 422 and order.json()["code"] == "not_tradable"


def test_metal_quotes_use_the_fresh_board_without_extra_credits(
    client: TestClient, forex: FakeProvider
) -> None:
    board = client.get("/api/v1/forex").json()
    deadline = clock.monotonic() + 10
    while board["as_of"] is None or board["refreshing"]:
        assert clock.monotonic() < deadline
        clock.sleep(0.05)
        board = client.get("/api/v1/forex").json()
    calls = len(forex.quote_priorities)
    quote = client.get("/api/v1/stocks/OANDA:XAU_USD/quote").json()
    assert "board" in quote["source"] and Decimal(quote["data"]["price"]) == Decimal("4000")
    inr = client.get("/api/v1/stocks/FX:EUR_INR/quote").json()  # derived cross, also free
    assert Decimal(inr["data"]["price"]) == Decimal("88")
    assert len(forex.quote_priorities) == calls


def test_unpriced_symbols_explain_why(client: TestClient) -> None:
    vod = client.get("/api/v1/stocks/VOD", params={"exchange": "L"}).json()
    assert vod["price_available"] is False
    assert "London Stock Exchange" in vod["price_note"] and vod["trade_note"] == vod["price_note"]
    aapl = client.get("/api/v1/stocks/AAPL").json()
    assert aapl["price_note"] is None and aapl["trade_note"] is None and aapl["quote_delay_min"] is None


def test_silver_is_explained_as_not_on_our_plan(client: TestClient, forex: FakeProvider) -> None:
    silver = client.get("/api/v1/stocks/OANDA:XAG_USD").json()
    assert silver["price_available"] is False
    assert (
        silver["price_note"]
        == "Silver prices aren't on our current data plan, so no price or chart will show."
    )
    calls = len(forex.quote_priorities)
    assert (
        client.get("/api/v1/quotes", params={"symbols": "OANDA:XAG_USD"}).json()["results"][0]["error"]
        == "unavailable"
    )
    assert len(forex.quote_priorities) == calls  # no call that's bound to fail


def test_inr_pairs_are_searchable(client: TestClient) -> None:
    results = client.get("/api/v1/search", params={"q": "rupee"}).json()["results"]
    assert {"USD/INR", "EUR/INR"} <= {r["display_symbol"] for r in results}
    assert all(r["price_available"] for r in results if r["exchange"] == "FX")


def test_forex_board_warms_lazily_and_derives_crosses(client: TestClient, forex: FakeProvider) -> None:
    first = client.get("/api/v1/forex").json()
    assert first["as_of"] is None and first["refreshing"] is True
    board = first
    deadline = clock.monotonic() + 10
    while board["as_of"] is None and clock.monotonic() < deadline:
        clock.sleep(0.05)
        board = client.get("/api/v1/forex").json()
    rows = {r["pair"]: r for r in board["rows"]}
    assert Decimal(rows["EUR/INR"]["rate"]) == Decimal("88") and rows["EUR/INR"]["derived"]
    assert rows["GBP/USD"]["rate"] is None  # not in this fake's quotes
    assert {c["code"] for c in board["currencies"]} >= {"USD", "INR", "XAU"}
    calls = len(forex.quote_priorities)
    client.get("/api/v1/forex")
    assert len(forex.quote_priorities) == calls  # a fresh snapshot isn't refetched


def test_macro_dashboard(container_and_client: tuple[Container, TestClient]) -> None:
    container, client = container_and_client
    container.providers = dataclasses.replace(
        container.providers,
        macro=FakeMacro({"FEDFUNDS": [(date(2026, 8, 1), "4.00"), (date(2026, 9, 1), "3.75")]}),
    )
    body = client.get("/api/v1/macro").json()
    assert body["configured"] is True
    fed = next(c for c in body["cards"] if c["id"] == "FEDFUNDS")
    assert Decimal(fed["latest"]["value"]) == Decimal("3.75") and Decimal(fed["change"]) == Decimal("-0.25")


def test_earnings_calendar_with_watchlist_filter(client: TestClient, provider: FakeProvider) -> None:
    def event(symbol: str, day: int, session: EarningsSession) -> EarningsEvent:
        return EarningsEvent(
            symbol=symbol, date=date(2026, 10, day), session=session, quarter=3, year=2026,
            eps_estimate=Decimal("1.00"), eps_actual=Decimal("1.10") if day == 20 else None,
            revenue_estimate=None, revenue_actual=None,
        )  # fmt: skip

    provider.earnings = [
        event("MSFT", 22, EarningsSession.AFTER_CLOSE),
        event("AAPL", 20, EarningsSession.BEFORE_OPEN),
        event("ZZZZ", 29, EarningsSession.UNKNOWN),  # next week
    ]
    week = client.get("/api/v1/calendar/earnings", params={"week": "2026-10-21"}).json()
    assert (week["week_start"], week["week_end"]) == ("2026-10-19", "2026-10-25")
    assert [e["symbol"] for e in week["events"]] == ["AAPL", "MSFT"]
    assert week["events"][0]["name"] == "APPLE INC" and week["events"][0]["eps_surprise_pct"] == "10.0"
    assert client.get("/api/v1/calendar/earnings", params={"watchlist_only": True}).status_code == 401

    headers = register(client)
    (watchlist,) = client.get("/api/v1/watchlists", headers=headers).json()
    client.post(f"/api/v1/watchlists/{watchlist['id']}/items", headers=headers, json={"symbol": "MSFT"})
    mine = client.get(
        "/api/v1/calendar/earnings", headers=headers, params={"week": "2026-10-21", "watchlist_only": True}
    ).json()
    assert [(e["symbol"], e["in_watchlist"]) for e in mine["events"]] == [("MSFT", True)]


def test_ipo_calendar(client: TestClient, provider: FakeProvider) -> None:
    provider.ipos = [
        IpoEvent(
            symbol="NEWCO",
            name="NewCo Inc",
            date=date(2026, 10, 23),
            exchange="NASDAQ Global",
            status="expected",
            price_range="18.00-20.00",
            shares=10_000_000,
            total_value=Decimal("200000000"),
        ),
    ]
    body = client.get("/api/v1/calendar/ipos", params={"week": "2026-10-20"}).json()
    assert [e["name"] for e in body["events"]] == ["NewCo Inc"]
    assert body["events"][0]["price_range"] == "18.00-20.00"

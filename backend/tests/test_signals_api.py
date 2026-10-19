import time as clock
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.container import Container
from app.main import create_app
from app.signals.engine import DISCLAIMER
from tests.api_helpers import file_db, make_settings, prepare
from tests.fakes import FakeProvider, news_item, trending_daily_bars
from tests.services.test_signals_and_briefs import LAST_SESSION
from tests.test_auth_and_portfolio_api import register


@pytest.fixture
def provider() -> FakeProvider:
    provider = FakeProvider()
    provider.bars = lambda *_: trending_daily_bars(LAST_SESSION, 260)
    provider.news = [news_item("Apple beats estimates", 1)]
    return provider


@pytest.fixture
def client(provider: FakeProvider, tmp_path: Path) -> Iterator[TestClient]:
    with TestClient(create_app(make_settings(database_url=file_db(tmp_path)))) as test_client:
        container: Container = test_client.app.state.container  # type: ignore[attr-defined]
        assert test_client.portal is not None
        test_client.portal.call(prepare, container, provider)
        yield test_client


def test_stock_signal_has_label_reasons_and_disclaimer(client: TestClient) -> None:
    body = client.get("/api/v1/stocks/AAPL/signal").json()
    assert body["label"] in {"Bullish signals", "Neutral", "Bearish signals"}
    assert body["reasons"] and all(r["reason"] for r in body["reasons"])
    assert body["disclaimer"] == DISCLAIMER
    assert any(s["rule"] == "news" for s in body["skipped"])  # one headline: too few to judge tone

    # Stored once: a second request returns the same record.
    assert client.get("/api/v1/stocks/AAPL/signal").json()["id"] == body["id"]

    history = client.get("/api/v1/signals/history", params={"symbol": "aapl"}).json()
    assert [h["id"] for h in history] == [body["id"]]
    labels = {
        h["label"] for h in client.get("/api/v1/signals/history", params={"label": body["label"]}).json()
    }
    assert labels == {body["label"]}


def test_signal_unavailable_for_non_us_symbols(client: TestClient) -> None:
    response = client.get("/api/v1/stocks/VOD/signal")
    assert response.status_code == 503 and response.json()["code"] == "unavailable"


def test_performance_reports_every_label_and_horizon(client: TestClient) -> None:
    body = client.get("/api/v1/signals/performance").json()
    assert body["total_signals"] == 0
    assert {(s["label"], s["horizon_days"]) for s in body["stats"]} == {
        (label, h) for label in ("Bullish signals", "Neutral", "Bearish signals") for h in (1, 5, 20)
    }
    assert body["disclaimer"] == DISCLAIMER


def test_brief_settings_and_on_demand_generation(client: TestClient) -> None:
    headers = register(client)
    status = client.get("/api/v1/brief", headers=headers).json()
    assert status["brief"] is None and status["generating"] is False

    updated = client.patch(
        "/api/v1/auth/me", headers=headers, json={"brief_time": "06:45", "brief_email_enabled": True}
    ).json()
    assert updated["brief_time"] == "06:45:00" and updated["brief_email_enabled"] is True

    (watchlist,) = client.get("/api/v1/watchlists", headers=headers).json()
    client.post(f"/api/v1/watchlists/{watchlist['id']}/items", headers=headers, json={"symbol": "AAPL"})

    assert client.post("/api/v1/brief/generate", headers=headers).status_code == 202
    deadline = clock.monotonic() + 10
    brief = None
    while clock.monotonic() < deadline:
        status = client.get("/api/v1/brief", headers=headers).json()
        if status["brief"] and not status["generating"]:
            brief = status["brief"]
            break
        clock.sleep(0.05)
    assert brief is not None, "brief was not generated"
    assert brief["disclaimer"] == DISCLAIMER and DISCLAIMER in brief["summary_md"]
    (item,) = brief["items"]
    assert item["source"] == "watchlist" and item["signal"]["symbol"] == "AAPL"
    assert brief["emailed_at"] is None  # SMTP isn't configured in tests

    listed = client.get("/api/v1/briefs", headers=headers).json()
    assert listed[0]["signal_count"] == 1
    assert (
        client.get(f"/api/v1/briefs/{listed[0]['brief_date']}", headers=headers).json()["id"] == brief["id"]
    )
    assert client.get("/api/v1/briefs/2001-01-01", headers=headers).status_code == 404


def test_brief_requires_auth(client: TestClient) -> None:
    assert client.get("/api/v1/brief").status_code == 401
    assert client.post("/api/v1/brief/generate").status_code == 401

from typing import Any

from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.config import Settings
from app.main import create_app
from tests.conftest import FAKE_FINNHUB_KEY


def make_settings(**overrides: Any) -> Settings:
    return Settings(_env_file=None, database_url="sqlite+aiosqlite:///:memory:", **overrides)


def test_health() -> None:
    with TestClient(create_app(make_settings())) as client:
        assert client.get("/health").json() == {"status": "ok"}


def test_system_status_reports_configuration_without_secrets() -> None:
    settings = make_settings(finnhub_api_key=SecretStr(FAKE_FINNHUB_KEY))
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/system/status")

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
    twelvedata = next(limiter for limiter in body["limiters"] if limiter["name"] == "twelvedata")
    assert twelvedata["daily_limit"] == 750

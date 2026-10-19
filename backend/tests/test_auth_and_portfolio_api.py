from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.auth import REFRESH_COOKIE
from app.container import Container
from app.main import create_app
from tests.api_helpers import file_db, make_settings, prepare
from tests.fakes import FakeProvider, make_quote

PASSWORD = "correct-horse-1"


@pytest.fixture
def provider() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def client(provider: FakeProvider, tmp_path: Path) -> Iterator[TestClient]:
    settings = make_settings(database_url=file_db(tmp_path), login_max_failures=3, refresh_reuse_grace_s=0)
    with TestClient(create_app(settings)) as test_client:
        container: Container = test_client.app.state.container  # type: ignore[attr-defined]
        assert test_client.portal is not None
        test_client.portal.call(prepare, container, provider)
        yield test_client


def register(client: TestClient, email: str = "alice@example.com") -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD, "display_name": "Alice", "timezone": "Asia/Kolkata"},
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def use_refresh_cookie(client: TestClient, value: str) -> None:
    """Make `value` the only refresh cookie. Setting one by hand while the server-set cookie (scoped to the
    test host) is still in the jar would send either of the two, which makes tests flaky."""
    client.cookies.clear()
    client.cookies.set(REFRESH_COOKIE, value, path="/api/v1/auth")


# --- auth -----------------------------------------------------------------------------------------


def test_register_returns_access_token_and_sets_httponly_refresh_cookie(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": " Alice@Example.com ", "password": PASSWORD, "timezone": "UTC"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["user"]["email"] == "alice@example.com"
    assert body["user"]["display_name"] == "alice"
    assert "refresh" not in response.text.lower().replace("refresh_token", "")  # never in the body
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{REFRESH_COOKIE}=")
    assert "HttpOnly" in cookie and "Path=/api/v1/auth" in cookie and "SameSite=lax" in cookie
    assert PASSWORD not in response.text


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ({"email": "not-an-email", "password": PASSWORD}, "invalid_email"),
        ({"email": "a@example.com", "password": "short"}, "invalid_password"),
        ({"email": "a@example.com", "password": PASSWORD, "timezone": "Mars/Base"}, "invalid_timezone"),
    ],
)
def test_register_validation(client: TestClient, payload: dict[str, str], code: str) -> None:
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 422
    assert response.json()["code"] == code


def test_duplicate_email_is_rejected(client: TestClient) -> None:
    register(client)
    response = client.post("/api/v1/auth/register", json={"email": "ALICE@example.com", "password": PASSWORD})
    assert response.status_code == 409
    assert response.json()["code"] == "email_taken"


def test_login_me_and_profile_update(client: TestClient) -> None:
    register(client)
    client.cookies.clear()
    bad = client.post("/api/v1/auth/login", json={"email": "alice@example.com", "password": "wrong-password"})
    assert bad.status_code == 401 and bad.json()["detail"] == "Incorrect email or password."
    unknown = client.post("/api/v1/auth/login", json={"email": "nobody@example.com", "password": PASSWORD})
    assert unknown.json()["detail"] == bad.json()["detail"]  # no account enumeration

    token = client.post(
        "/api/v1/auth/login", json={"email": "alice@example.com", "password": PASSWORD}
    ).json()
    headers = {"Authorization": f"Bearer {token['access_token']}"}
    assert client.get("/api/v1/auth/me", headers=headers).json()["timezone"] == "Asia/Kolkata"

    updated = client.patch(
        "/api/v1/auth/me", headers=headers, json={"display_name": "Al", "timezone": "Europe/Paris"}
    )
    assert updated.json()["display_name"] == "Al" and updated.json()["timezone"] == "Europe/Paris"
    assert client.patch("/api/v1/auth/me", headers=headers, json={"timezone": "Nope/Nope"}).status_code == 422


def test_protected_endpoints_require_a_valid_token(client: TestClient) -> None:
    assert client.get("/api/v1/auth/me").json()["code"] == "not_authenticated"
    expired = client.get("/api/v1/watchlists", headers={"Authorization": "Bearer garbage"})
    assert expired.status_code == 401 and expired.json()["code"] == "token_expired"


def test_repeated_failed_logins_are_throttled(client: TestClient) -> None:
    register(client)
    for _ in range(3):
        client.post("/api/v1/auth/login", json={"email": "alice@example.com", "password": "wrong-password"})
    locked = client.post("/api/v1/auth/login", json={"email": "alice@example.com", "password": PASSWORD})
    assert locked.status_code == 429


def test_refresh_rotates_and_detects_reuse(client: TestClient) -> None:
    register(client)
    first_cookie = client.cookies.get(REFRESH_COOKIE)
    assert first_cookie

    rotated = client.post("/api/v1/auth/refresh")
    assert rotated.status_code == 200
    second_cookie = client.cookies.get(REFRESH_COOKIE)
    assert second_cookie and second_cookie != first_cookie

    # Replaying the old token (e.g. stolen) is refused and ends every session, including the new one.
    use_refresh_cookie(client, first_cookie)
    assert client.post("/api/v1/auth/refresh").status_code == 401
    use_refresh_cookie(client, second_cookie)
    assert client.post("/api/v1/auth/refresh").status_code == 401


def test_logout_revokes_the_refresh_token(client: TestClient) -> None:
    register(client)
    cookie = client.cookies.get(REFRESH_COOKIE)
    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.cookies.get(REFRESH_COOKIE) is None
    use_refresh_cookie(client, cookie or "")
    assert client.post("/api/v1/auth/refresh").status_code == 401


def test_cookie_endpoints_reject_foreign_origins(client: TestClient) -> None:
    register(client)
    response = client.post("/api/v1/auth/refresh", headers={"Origin": "https://evil.example"})
    assert response.status_code == 403
    assert client.post("/api/v1/auth/refresh", headers={"Origin": "http://localhost:3000"}).status_code == 200


# --- watchlists & quotes ----------------------------------------------------------------------------


def test_watchlist_crud_and_isolation(client: TestClient) -> None:
    alice = register(client, "alice@example.com")
    bob = register(client, "bob@example.com")

    (default,) = client.get("/api/v1/watchlists", headers=alice).json()
    added = client.post(f"/api/v1/watchlists/{default['id']}/items", headers=alice, json={"symbol": "aapl"})
    assert added.status_code == 201
    assert [s["symbol"] for s in added.json()["symbols"]] == ["AAPL"]
    assert (
        client.post(
            f"/api/v1/watchlists/{default['id']}/items", headers=alice, json={"symbol": "NOPE"}
        ).json()["code"]
        == "not_found"
    )

    created = client.post("/api/v1/watchlists", headers=alice, json={"name": "Europe"}).json()
    renamed = client.patch(f"/api/v1/watchlists/{created['id']}", headers=alice, json={"name": "EU"}).json()
    assert renamed["name"] == "EU"

    # Bob sees only his own default list and can't touch Alice's.
    assert [w["name"] for w in client.get("/api/v1/watchlists", headers=bob).json()] == ["My watchlist"]
    assert client.delete(f"/api/v1/watchlists/{created['id']}", headers=bob).status_code == 404
    assert client.delete(f"/api/v1/watchlists/{default['id']}/items/AAPL", headers=bob).status_code == 404

    assert client.delete(f"/api/v1/watchlists/{default['id']}/items/AAPL", headers=alice).status_code == 204
    assert client.delete(f"/api/v1/watchlists/{created['id']}", headers=alice).status_code == 204


def test_bulk_quotes_report_per_symbol_status(client: TestClient, provider: FakeProvider) -> None:
    provider.quotes["AAPL"] = make_quote("AAPL", "250")
    results = client.get("/api/v1/quotes", params={"symbols": "AAPL,MSFT,VOD,ZZZZ"}).json()["results"]
    by_symbol = {r["symbol"]: r for r in results}
    assert Decimal(by_symbol["AAPL"]["quote"]["data"]["price"]) == Decimal("250")
    assert by_symbol["MSFT"]["error"] == "unavailable"  # fake provider has no MSFT quote
    assert by_symbol["VOD"]["error"] == "unavailable"  # non-US: not on our data plan
    assert by_symbol["ZZZZ"]["error"] == "not_found"


# --- paper trading ----------------------------------------------------------------------------------


def test_trading_flow(client: TestClient, provider: FakeProvider) -> None:
    headers = register(client)
    provider.quotes["AAPL"] = make_quote("AAPL", "200")

    portfolio = client.get("/api/v1/portfolio", headers=headers).json()
    assert Decimal(portfolio["cash"]) == Decimal("100000") and portfolio["positions"] == []

    buy = client.post(
        "/api/v1/portfolio/orders", headers=headers, json={"symbol": "AAPL", "side": "buy", "quantity": "2.5"}
    )
    assert buy.status_code == 201, buy.text
    assert Decimal(buy.json()["notional"]) == Decimal("500")

    provider.quotes["AAPL"] = make_quote("AAPL", "220")
    portfolio = client.get("/api/v1/portfolio", headers=headers).json()
    (position,) = portfolio["positions"]
    assert Decimal(position["unrealized_pnl"]) == Decimal("50")
    assert Decimal(portfolio["equity"]) == Decimal("100050")

    sell = client.post(
        "/api/v1/portfolio/orders", headers=headers, json={"symbol": "AAPL", "side": "sell", "quantity": "1"}
    )
    assert Decimal(sell.json()["realized_pnl"]) == Decimal("20")

    too_much = client.post(
        "/api/v1/portfolio/orders", headers=headers, json={"symbol": "AAPL", "side": "sell", "quantity": "5"}
    )
    assert too_much.status_code == 422 and too_much.json()["code"] == "insufficient_shares"
    bad_qty = client.post(
        "/api/v1/portfolio/orders", headers=headers, json={"symbol": "AAPL", "side": "buy", "quantity": "-1"}
    )
    assert bad_qty.status_code == 422

    trades = client.get("/api/v1/portfolio/trades", headers=headers).json()
    assert [t["side"] for t in trades] == ["sell", "buy"]

    reset = client.post("/api/v1/portfolio/reset", headers=headers).json()
    assert Decimal(reset["cash"]) == Decimal("100000") and reset["positions"] == []
    assert client.get("/api/v1/portfolio/trades", headers=headers).json() == []


def test_portfolio_requires_auth(client: TestClient) -> None:
    assert client.get("/api/v1/portfolio").status_code == 401
    assert (
        client.post(
            "/api/v1/portfolio/orders", json={"symbol": "AAPL", "side": "buy", "quantity": "1"}
        ).status_code
        == 401
    )

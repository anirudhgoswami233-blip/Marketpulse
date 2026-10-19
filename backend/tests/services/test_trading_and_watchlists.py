from decimal import Decimal as D

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.cache import Fetched
from app.core.errors import Conflict, NotFound, ProviderUnavailable, ValidationFailed
from app.models import Portfolio, Position, Symbol, Trade
from app.providers.base import Quote
from app.services import auth_service, symbol_directory, trading_service, watchlist_service
from app.services.search_service import resolve_symbol
from app.services.trading_service import ConcurrentUpdate, PriceUnavailable, Side
from app.ws.hub import PriceHub
from tests.api_helpers import make_settings
from tests.fakes import FakeProvider, make_quote
from tests.services.test_search_and_quotes import rec

SETTINGS = make_settings()


@pytest.fixture
async def ctx(session_factory: async_sessionmaker[AsyncSession]) -> dict[str, object]:
    async with session_factory() as session:
        await symbol_directory.upsert_exchanges(session, symbol_directory.load_exchange_rows())
        await symbol_directory.upsert_symbols(
            session, "US", [rec("AAPL", "APPLE INC"), rec("MSFT", "MICROSOFT")]
        )
        await symbol_directory.upsert_symbols(session, "L", [rec("VOD", "VODAFONE")])
        alice = await auth_service.register(
            session, SETTINGS, "alice@example.com", "password123", "Alice", "UTC"
        )
        bob = await auth_service.register(session, SETTINGS, "bob@example.com", "password123", "Bob", "UTC")
        await session.commit()
        return {"alice": alice.id, "bob": bob.id}


def provider_with(**prices: str) -> FakeProvider:
    provider = FakeProvider()
    for symbol, price in prices.items():
        provider.quotes[symbol] = make_quote(symbol, price)
    return provider


async def order(
    session: AsyncSession, provider: FakeProvider, user_id: int, symbol: str, side: Side, qty: str
) -> Trade:
    sym = await resolve_symbol(session, symbol)
    return await trading_service.place_order(session, provider, PriceHub(), user_id, sym, side, D(qty))


async def test_new_accounts_get_funded_portfolio_and_watchlist(
    session_factory: async_sessionmaker[AsyncSession], ctx: dict[str, int]
) -> None:
    async with session_factory() as session:
        portfolio = await trading_service.get_portfolio(session, ctx["alice"])
        lists = await watchlist_service.list_watchlists(session, ctx["alice"])
    assert portfolio.cash == D("100000") and portfolio.base_currency == "USD"
    assert [v.watchlist.name for v in lists] == ["My watchlist"]


async def test_buy_then_sell_updates_cash_position_and_realized_pnl(
    session_factory: async_sessionmaker[AsyncSession], ctx: dict[str, int]
) -> None:
    provider = provider_with(AAPL="100")
    async with session_factory() as session:
        await order(session, provider, ctx["alice"], "AAPL", Side.BUY, "10")
        provider.quotes["AAPL"] = make_quote("AAPL", "130")
        await order(session, provider, ctx["alice"], "AAPL", Side.BUY, "5")
        provider.quotes["AAPL"] = make_quote("AAPL", "150")
        sell = await order(session, provider, ctx["alice"], "AAPL", Side.SELL, "3")

        portfolio = await trading_service.get_portfolio(session, ctx["alice"])
        position = (await session.execute(select(Position))).scalar_one()

    assert sell.realized_pnl == D("120.000000")  # (150 - 110) * 3
    assert position.quantity == D(12) and position.avg_cost == D("110")
    assert portfolio.cash == D("100000") - D("1000") - D("650") + D("450")
    assert portfolio.version == 3


async def test_selling_entire_position_removes_it(
    session_factory: async_sessionmaker[AsyncSession], ctx: dict[str, int]
) -> None:
    provider = provider_with(AAPL="100")
    async with session_factory() as session:
        await order(session, provider, ctx["alice"], "AAPL", Side.BUY, "0.5")
        await order(session, provider, ctx["alice"], "AAPL", Side.SELL, "0.5")
        assert (await session.execute(select(Position))).first() is None


@pytest.mark.parametrize(
    ("side", "qty", "code"),
    [(Side.BUY, "2000", "insufficient_cash"), (Side.SELL, "1", "insufficient_shares")],
)
async def test_order_validation(
    session_factory: async_sessionmaker[AsyncSession], ctx: dict[str, int], side: Side, qty: str, code: str
) -> None:
    provider = provider_with(AAPL="100")
    async with session_factory() as session:
        with pytest.raises(ValidationFailed) as exc_info:
            await order(session, provider, ctx["alice"], "AAPL", side, qty)
    assert exc_info.value.code == code


async def test_non_us_symbols_are_not_tradable(
    session_factory: async_sessionmaker[AsyncSession], ctx: dict[str, int]
) -> None:
    async with session_factory() as session:
        vod = await resolve_symbol(session, "VOD")
        with pytest.raises(ValidationFailed, match="can't be traded"):
            await trading_service.place_order(
                session, provider_with(), PriceHub(), ctx["alice"], vod, Side.BUY, D(1)
            )


async def test_orders_are_refused_on_stale_or_missing_prices(
    session_factory: async_sessionmaker[AsyncSession], ctx: dict[str, int]
) -> None:
    class StaleProvider(FakeProvider):
        async def get_quote(self, symbol: str) -> Fetched[Quote]:
            return Fetched[Quote](
                data=make_quote(symbol, "100"), as_of=self.as_of, source=self.name, stale=True
            )

    async with session_factory() as session:
        with pytest.raises(PriceUnavailable, match="delayed"):
            await order(session, StaleProvider(), ctx["alice"], "AAPL", Side.BUY, "1")
        provider = FakeProvider()
        provider.quote_errors["AAPL"] = ProviderUnavailable("fake", "down")
        with pytest.raises(PriceUnavailable):
            await order(session, provider, ctx["alice"], "AAPL", Side.BUY, "1")


async def test_concurrent_change_is_retried_then_succeeds(
    session_factory: async_sessionmaker[AsyncSession],
    ctx: dict[str, int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Simulate another order committing between our read and our write: we must re-read, not overwrite."""
    provider = provider_with(AAPL="100")
    original = trading_service._execute
    calls = {"n": 0}

    async def interfering(session: AsyncSession, portfolio: Portfolio, *args: object) -> Trade:
        calls["n"] += 1
        if calls["n"] == 1:
            async with session_factory() as other:
                await other.execute(
                    update(Portfolio)
                    .where(Portfolio.id == portfolio.id)
                    .values(cash=Portfolio.cash - 500, version=Portfolio.version + 1)
                )
                await other.commit()
        return await original(session, portfolio, *args)  # type: ignore[arg-type]

    monkeypatch.setattr(trading_service, "_execute", interfering)
    async with session_factory() as session:
        await order(session, provider, ctx["alice"], "AAPL", Side.BUY, "1")
        portfolio = await trading_service.get_portfolio(session, ctx["alice"])
    assert calls["n"] == 2
    assert portfolio.cash == D("100000") - D("500") - D("100")  # both changes kept


async def test_persistent_conflicts_give_up(
    session_factory: async_sessionmaker[AsyncSession], ctx: dict[str, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def always_conflict(*_: object) -> Trade:
        raise ConcurrentUpdate("portfolio changed")

    monkeypatch.setattr(trading_service, "_execute", always_conflict)
    async with session_factory() as session:
        with pytest.raises(ConcurrentUpdate):
            await order(session, provider_with(AAPL="100"), ctx["alice"], "AAPL", Side.BUY, "1")


@pytest.mark.parametrize("raw", ["0", "-1", "1.1234567", "NaN", "abc", "1e12"])
def test_quantity_parsing_rejects_bad_input(raw: str) -> None:
    with pytest.raises(ValidationFailed):
        trading_service.parse_quantity(raw)


def test_quantity_parsing_accepts_fractions() -> None:
    assert trading_service.parse_quantity("0.123456") == D("0.123456")


async def test_valuation_marks_unpriced_positions(
    session_factory: async_sessionmaker[AsyncSession], ctx: dict[str, int]
) -> None:
    provider = provider_with(AAPL="100", MSFT="200")
    async with session_factory() as session:
        await order(session, provider, ctx["alice"], "AAPL", Side.BUY, "10")
        await order(session, provider, ctx["alice"], "MSFT", Side.BUY, "1")
        provider.quotes["AAPL"] = make_quote("AAPL", "110")
        del provider.quotes["MSFT"]  # now unpriced: valued at cost, flagged incomplete
        portfolio = await trading_service.get_portfolio(session, ctx["alice"])
        view = await trading_service.value_portfolio(session, provider, PriceHub(), portfolio)

    by_symbol = {p.symbol.symbol: p for p in view.positions}
    assert by_symbol["AAPL"].valuation is not None
    assert by_symbol["AAPL"].valuation.unrealized_pnl == D("100.000000")
    assert by_symbol["MSFT"].valuation is None
    assert view.incomplete
    assert view.totals.equity == D("100000") - D("1000") - D("200") + D("1100") + D("200")


async def test_reset_restores_cash_and_clears_history(
    session_factory: async_sessionmaker[AsyncSession], ctx: dict[str, int]
) -> None:
    async with session_factory() as session:
        await order(session, provider_with(AAPL="100"), ctx["alice"], "AAPL", Side.BUY, "10")
        portfolio = await trading_service.reset_portfolio(session, ctx["alice"])
        assert portfolio.cash == D("100000")
        assert (await session.execute(select(Trade))).first() is None
        assert (await session.execute(select(Position))).first() is None


async def test_watchlists_are_private_and_validated(
    session_factory: async_sessionmaker[AsyncSession], ctx: dict[str, int]
) -> None:
    async with session_factory() as session:
        tech = await watchlist_service.create_watchlist(session, SETTINGS, ctx["alice"], "  Big   tech ")
        assert tech.name == "Big tech"
        await watchlist_service.add_symbol(session, SETTINGS, ctx["alice"], tech.id, "aapl")

        with pytest.raises(Conflict):
            await watchlist_service.add_symbol(session, SETTINGS, ctx["alice"], tech.id, "AAPL")
        with pytest.raises(Conflict):
            await watchlist_service.create_watchlist(session, SETTINGS, ctx["alice"], "big TECH")
        with pytest.raises(ValidationFailed):
            await watchlist_service.create_watchlist(session, SETTINGS, ctx["alice"], "   ")
        # Bob can't see, edit or delete Alice's list: it simply doesn't exist for him.
        with pytest.raises(NotFound):
            await watchlist_service.add_symbol(session, SETTINGS, ctx["bob"], tech.id, "MSFT")
        with pytest.raises(NotFound):
            await watchlist_service.delete_watchlist(session, ctx["bob"], tech.id)

        view = await watchlist_service.get_watchlist(session, ctx["alice"], tech.id)
        assert [s.symbol for s in view.symbols] == ["AAPL"]

        await watchlist_service.remove_symbol(session, ctx["alice"], tech.id, "aapl")
        await watchlist_service.delete_watchlist(session, ctx["alice"], tech.id)
        assert [v.watchlist.name for v in await watchlist_service.list_watchlists(session, ctx["alice"])] == [
            "My watchlist"
        ]


async def test_watchlist_limits(
    session_factory: async_sessionmaker[AsyncSession], ctx: dict[str, int]
) -> None:
    tight = make_settings(max_watchlists_per_user=2, max_watchlist_items=1)
    async with session_factory() as session:
        extra = await watchlist_service.create_watchlist(session, tight, ctx["alice"], "Second")
        with pytest.raises(ValidationFailed, match="up to 2"):
            await watchlist_service.create_watchlist(session, tight, ctx["alice"], "Third")
        await watchlist_service.add_symbol(session, tight, ctx["alice"], extra.id, "AAPL")
        with pytest.raises(ValidationFailed, match="up to 1"):
            await watchlist_service.add_symbol(session, tight, ctx["alice"], extra.id, "MSFT")
        symbols = (await session.execute(select(Symbol.symbol))).scalars().all()
    assert "MSFT" in symbols


async def test_refresh_race_within_grace_window_does_not_revoke_everything(
    session_factory: async_sessionmaker[AsyncSession], ctx: dict[str, int]
) -> None:
    from datetime import UTC, datetime, timedelta

    from app.core.errors import Unauthorized
    from app.core.security import TokenSigner

    signer = TokenSigner(secret="x" * 40, access_ttl=timedelta(minutes=15))
    now = datetime.now(UTC)
    async with session_factory() as session:
        user = await auth_service.authenticate(
            session, FakeProvider().cache, SETTINGS, "alice@example.com", "password123", "test"
        )
        first = await auth_service.issue_session(session, signer, SETTINGS, user, now)
        second = await auth_service.rotate_session(session, signer, SETTINGS, first.refresh_token, now)
        await session.commit()

        # Another tab presents the old token 5s later: a race, not theft.
        with pytest.raises(Unauthorized) as race:
            await auth_service.rotate_session(
                session, signer, SETTINGS, first.refresh_token, now + timedelta(seconds=5)
            )
        assert race.value.code == "refresh_race"
        third = await auth_service.rotate_session(
            session, signer, SETTINGS, second.refresh_token, now + timedelta(seconds=6)
        )
        await session.commit()

        # Long after rotation, the same replay is treated as theft and ends every session.
        with pytest.raises(Unauthorized) as theft:
            await auth_service.rotate_session(
                session, signer, SETTINGS, first.refresh_token, now + timedelta(minutes=10)
            )
        assert theft.value.code == "invalid_refresh"
        with pytest.raises(Unauthorized):
            await auth_service.rotate_session(
                session, signer, SETTINGS, third.refresh_token, now + timedelta(minutes=10)
            )

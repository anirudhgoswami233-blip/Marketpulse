from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import SymbolNotFound
from app.providers.base import SymbolRecord
from app.services import quote_service, search_service, symbol_directory
from app.ws.hub import PriceHub, Trade
from tests.fakes import FakeProvider, make_quote


def rec(symbol: str, description: str, type_: str = "Common Stock") -> SymbolRecord:
    return SymbolRecord(
        symbol=symbol,
        display_symbol=symbol,
        description=description,
        type=type_,
        currency="USD",
        mic="XNAS",
        figi=None,
    )


@pytest.fixture
async def seeded(session_factory: async_sessionmaker[AsyncSession]) -> async_sessionmaker[AsyncSession]:
    async with session_factory() as session:
        await symbol_directory.upsert_exchanges(session, symbol_directory.load_exchange_rows())
        await symbol_directory.upsert_symbols(
            session,
            "US",
            [
                rec("AAPL", "APPLE INC"),
                rec("AAPLW", "APPLE WARRANT", "Warrant"),
                rec("APLE", "APPLE HOSPITALITY REIT INC"),
                rec("PINE", "PINEAPPLE ENERGY"),
                rec("A", "AGILENT TECHNOLOGIES"),
                rec("PCT", "100% PURE CO"),
                rec("AIQD", "MICROSECTORS -3X AI", "ETP"),
                rec("MSFT", "MICROSOFT CORP"),
            ],
        )
        await symbol_directory.upsert_symbols(session, "L", [rec("AAPL", "APPLE INC (LSE CDI)")])
        await session.commit()
    return session_factory


async def test_search_ranks_exact_then_prefix_then_name(seeded: async_sessionmaker[AsyncSession]) -> None:
    async with seeded() as session:
        results = await search_service.search_symbols(session, "aapl")
    assert [(s.symbol, s.exchange_code) for s in results][:2] in (
        [("AAPL", "US"), ("AAPL", "L")],
        [("AAPL", "L"), ("AAPL", "US")],
    )
    assert results[-1].symbol == "AAPLW"


async def test_search_matches_company_names(seeded: async_sessionmaker[AsyncSession]) -> None:
    async with seeded() as session:
        results = await search_service.search_symbols(session, "apple")
    symbols = [s.symbol for s in results]
    assert symbols[0] in {
        "AAPL",
        "APLE",
    }  # names starting with "apple" come before names merely containing it
    assert symbols.index("PINE") > symbols.index("APLE")


async def test_search_prefers_companies_over_funds(seeded: async_sessionmaker[AsyncSession]) -> None:
    async with seeded() as session:
        results = await search_service.search_symbols(session, "micro")
    assert [s.symbol for s in results] == ["MSFT", "AIQD"]


async def test_search_escapes_like_wildcards(seeded: async_sessionmaker[AsyncSession]) -> None:
    async with seeded() as session:
        assert [s.symbol for s in await search_service.search_symbols(session, "100%")] == ["PCT"]
        assert await search_service.search_symbols(session, "   ") == []


async def test_resolve_prefers_us_listing(seeded: async_sessionmaker[AsyncSession]) -> None:
    async with seeded() as session:
        assert (await search_service.resolve_symbol(session, "aapl")).exchange_code == "US"
        assert (await search_service.resolve_symbol(session, "AAPL", "L")).exchange_code == "L"
        with pytest.raises(SymbolNotFound):
            await search_service.resolve_symbol(session, "NOPE")


async def test_quote_gets_currency_and_newer_trade_overlay(seeded: async_sessionmaker[AsyncSession]) -> None:
    provider, hub = FakeProvider(), PriceHub()
    provider.quotes["AAPL"] = make_quote("AAPL", "100", "0", prev_close="100")
    hub.publish(
        Trade(symbol="AAPL", price=Decimal("102.5"), timestamp=datetime(2026, 10, 19, 14, 30, tzinfo=UTC))
    )
    async with seeded() as session:
        symbol = await search_service.resolve_symbol(session, "AAPL")

    result = await quote_service.get_quote(provider, hub, symbol)

    assert result.data.currency == "USD"
    assert result.data.price == Decimal("102.5")
    assert result.data.change == Decimal("2.5")
    assert result.data.change_pct == Decimal("2.5000")
    assert result.data.high == Decimal("102.5")


async def test_quote_ignores_older_trade(seeded: async_sessionmaker[AsyncSession]) -> None:
    provider, hub = FakeProvider(), PriceHub()
    provider.quotes["AAPL"] = make_quote("AAPL", "100")
    hub.publish(
        Trade(symbol="AAPL", price=Decimal("90"), timestamp=datetime(2026, 10, 19, 13, 0, tzinfo=UTC))
    )
    async with seeded() as session:
        symbol = await search_service.resolve_symbol(session, "AAPL")
    assert (await quote_service.get_quote(provider, hub, symbol)).data.price == Decimal("100")

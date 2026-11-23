from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.cache import MemoryCache
from app.services import auth_service, news_digest_service, symbol_directory, watchlist_service
from tests.api_helpers import make_settings
from tests.fakes import FakeProvider, news_item
from tests.services.test_search_and_quotes import rec

SETTINGS = make_settings()
NOW = datetime(2026, 10, 20, 15, 0, tzinfo=UTC)


@pytest.fixture
async def user_with_watchlist(session_factory: async_sessionmaker[AsyncSession]) -> int:
    async with session_factory() as session:
        await symbol_directory.upsert_exchanges(session, symbol_directory.load_exchange_rows())
        await symbol_directory.upsert_symbols(
            session, "US", [rec("AAPL", "APPLE INC"), rec("MSFT", "MICROSOFT")]
        )
        user = await auth_service.register(
            session, SETTINGS, "d@example.com", "password123", "D", "UTC", date(1990, 1, 1)
        )
        (wl,) = await watchlist_service.list_watchlists(session, user.id)
        await watchlist_service.add_symbol(session, SETTINGS, user.id, wl.watchlist.id, "AAPL")
        await watchlist_service.add_symbol(session, SETTINGS, user.id, wl.watchlist.id, "MSFT")
        await session.commit()
        return user.id


def _provider() -> FakeProvider:
    provider = FakeProvider()
    provider.news = [
        news_item("Apple names new head of design", 0),  # other -> low (excluded)
        news_item("Company beats estimates on record revenue", 1),  # earnings -> high
        news_item("Analysts upgrade the stock, raise price target", 2),  # rating -> medium
    ]
    return provider


def test_needs_refresh() -> None:
    snap = news_digest_service.DigestSnapshot()
    assert news_digest_service.needs_refresh(snap, NOW)
    snap.completed_at = NOW
    assert not news_digest_service.needs_refresh(snap, NOW)
    later = NOW + news_digest_service.DIGEST_MAX_AGE + timedelta(seconds=1)
    assert news_digest_service.needs_refresh(snap, later)


async def test_digest_aggregates_material_news_most_material_first(
    session_factory: async_sessionmaker[AsyncSession], user_with_watchlist: int
) -> None:
    provider, cache = _provider(), MemoryCache()
    async with session_factory() as session:
        symbols = await news_digest_service.watched_symbols(session, user_with_watchlist)
        assert {s.symbol for s in symbols} == {"AAPL", "MSFT"}
        await news_digest_service.refresh_digest(provider, cache, user_with_watchlist, symbols, NOW)
        out = await news_digest_service.get_digest(session, cache, user_with_watchlist, NOW, refreshing=False)

    assert out.symbols_total == 2
    assert out.as_of == NOW and out.stale is False
    # Both watched symbols yield the same fake news: one high + one medium each = 4 material items.
    assert len(out.items) == 4
    assert out.items[0].materiality == "high"  # most material sorts first
    assert all(i.materiality in ("high", "medium") for i in out.items)
    assert all("design" not in i.headline for i in out.items)  # low-materiality dropped


async def test_digest_drops_news_for_removed_symbols(
    session_factory: async_sessionmaker[AsyncSession], user_with_watchlist: int
) -> None:
    provider, cache = _provider(), MemoryCache()
    async with session_factory() as session:
        symbols = await news_digest_service.watched_symbols(session, user_with_watchlist)
        await news_digest_service.refresh_digest(provider, cache, user_with_watchlist, symbols, NOW)
        (wl,) = await watchlist_service.list_watchlists(session, user_with_watchlist)
        await watchlist_service.remove_symbol(session, user_with_watchlist, wl.watchlist.id, "MSFT")
        out = await news_digest_service.get_digest(session, cache, user_with_watchlist, NOW, refreshing=False)

    assert out.symbols_total == 1
    assert out.items and all(i.symbol == "AAPL" for i in out.items)

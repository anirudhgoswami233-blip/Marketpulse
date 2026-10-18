from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.cache import MemoryCache
from app.core.errors import ProviderError
from app.models import PriceBar, Symbol
from app.providers.base import Bar, Interval, NewsItem, SymbolRecord
from app.services import history_service, search_service, stock_service, symbol_directory
from app.services.stock_service import ChartRange
from tests.fakes import FakeProvider, daily_bar

MON_MIDDAY = datetime(2026, 10, 19, 16, 0, tzinfo=UTC)  # 12:00 New York; last completed session = Fri 16th


def weekdays(end: date, count: int) -> list[date]:
    days: list[date] = []
    day = end
    while len(days) < count:
        if day.weekday() < 5:
            days.append(day)
        day -= timedelta(days=1)
    return sorted(days)


@pytest.fixture
async def aapl(session_factory: async_sessionmaker[AsyncSession]) -> Symbol:
    async with session_factory() as session:
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
        await session.commit()
        return await search_service.resolve_symbol(session, "AAPL")


async def bar_count(session: AsyncSession) -> int:
    return (await session.execute(select(func.count()).select_from(PriceBar))).scalar_one()


async def test_first_fetch_stores_completed_sessions_only(
    session_factory: async_sessionmaker[AsyncSession], aapl: Symbol
) -> None:
    provider, cache = FakeProvider(), MemoryCache()
    # Provider includes today's in-progress bar (Mon 19th), which must not be stored as final.
    provider.bars = lambda *_: [daily_bar(d) for d in weekdays(date(2026, 10, 19), 10)]

    async with session_factory() as session:
        result = await history_service.get_daily_bars(
            session, provider, cache, aapl, date(2026, 10, 1), MON_MIDDAY
        )
        assert await bar_count(session) == 9

    assert provider.bars_calls == [("AAPL", Interval.DAY_1, history_service.FULL_HISTORY_BARS)]
    assert result.data.bars[-1].timestamp.date() == date(2026, 10, 16)
    assert result.as_of == datetime(2026, 10, 16, 20, 0, tzinfo=UTC)  # Friday 16:00 New York
    assert not result.stale


async def test_up_to_date_history_is_served_from_db(
    session_factory: async_sessionmaker[AsyncSession], aapl: Symbol
) -> None:
    provider, cache = FakeProvider(), MemoryCache()
    provider.bars = lambda *_: [daily_bar(d) for d in weekdays(date(2026, 10, 16), 5)]
    async with session_factory() as session:
        await history_service.get_daily_bars(session, provider, cache, aapl, date(2026, 10, 1), MON_MIDDAY)
        await history_service.get_daily_bars(session, provider, cache, aapl, date(2026, 10, 1), MON_MIDDAY)
    assert len(provider.bars_calls) == 1


async def test_topup_requests_only_missing_days(
    session_factory: async_sessionmaker[AsyncSession], aapl: Symbol
) -> None:
    provider, cache = FakeProvider(), MemoryCache()
    provider.bars = lambda *_: [daily_bar(d) for d in weekdays(date(2026, 10, 14), 5)]
    async with session_factory() as session:
        await history_service.get_daily_bars(
            session, provider, cache, aapl, date(2026, 10, 1), datetime(2026, 10, 14, 21, 0, tzinfo=UTC)
        )
        provider.bars = lambda *_: [daily_bar(d, "105") for d in weekdays(date(2026, 10, 16), 3)]
        result = await history_service.get_daily_bars(
            session, provider, cache, aapl, date(2026, 10, 1), MON_MIDDAY
        )
    assert provider.bars_calls[-1][2] == 2 + history_service.TOPUP_PADDING_BARS
    assert result.data.bars[-1].close == Decimal("105")


async def test_provider_failure_serves_stored_bars_as_stale(
    session_factory: async_sessionmaker[AsyncSession], aapl: Symbol
) -> None:
    provider, cache = FakeProvider(), MemoryCache()
    provider.bars = lambda *_: [daily_bar(d) for d in weekdays(date(2026, 10, 14), 5)]
    async with session_factory() as session:
        await history_service.get_daily_bars(
            session, provider, cache, aapl, date(2026, 10, 1), datetime(2026, 10, 14, 21, 0, tzinfo=UTC)
        )
        provider.bars = ProviderError("fake", "down")
        result = await history_service.get_daily_bars(
            session, provider, cache, aapl, date(2026, 10, 1), MON_MIDDAY
        )
        assert result.stale and len(result.data.bars) == 5

        # The failed attempt is remembered, so the next request doesn't hit the provider again.
        await history_service.get_daily_bars(session, provider, cache, aapl, date(2026, 10, 1), MON_MIDDAY)
    assert len(provider.bars_calls) == 2


async def test_provider_failure_without_history_raises(
    session_factory: async_sessionmaker[AsyncSession], aapl: Symbol
) -> None:
    provider = FakeProvider()
    provider.bars = ProviderError("fake", "down")
    async with session_factory() as session:
        with pytest.raises(ProviderError):
            await history_service.get_daily_bars(
                session, provider, MemoryCache(), aapl, date(2026, 10, 1), MON_MIDDAY
            )


def intraday(day: date, hour: int, minute: int) -> Bar:
    ts = datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC)
    return Bar(timestamp=ts, open=Decimal(1), high=Decimal(1), low=Decimal(1), close=Decimal(1), volume=None)


def test_last_sessions_groups_by_exchange_local_date() -> None:
    bars = [
        intraday(date(2026, 10, 15), 19, 55),  # Thu 15:55 NY
        intraday(date(2026, 10, 16), 13, 30),  # Fri 09:30 NY
        intraday(date(2026, 10, 16), 19, 55),  # Fri 15:55 NY
    ]
    kept = stock_service.last_sessions(bars, 1, "America/New_York")
    assert [b.timestamp.day for b in kept] == [16, 16]


async def test_intraday_chart_uses_provider_and_keeps_last_session(
    session_factory: async_sessionmaker[AsyncSession], aapl: Symbol
) -> None:
    provider = FakeProvider()
    provider.bars = lambda *_: [intraday(date(2026, 10, 15), 19, 0), intraday(date(2026, 10, 16), 14, 0)]
    async with session_factory() as session:
        chart = await stock_service.get_chart(
            session, provider, MemoryCache(), aapl, ChartRange.D1, MON_MIDDAY
        )
    assert provider.bars_calls == [("AAPL", Interval.MIN_5, 160)]
    assert len(chart.data.bars) == 1
    assert chart.data.currency == "USD" and chart.data.range == "1D"


async def test_news_sorted_newest_first_and_limited(aapl: Symbol) -> None:
    provider = FakeProvider()
    provider.news = [
        NewsItem(
            id=str(i),
            headline=f"h{i}",
            summary="",
            source="s",
            url="u",
            image_url=None,
            published_at=datetime(2026, 10, 1, tzinfo=UTC) + timedelta(hours=i),
            category=None,
            related_symbols=[],
        )
        for i in range(30)
    ]
    news = await stock_service.get_news(provider, aapl, date(2026, 10, 19))
    assert len(news.data) == stock_service.NEWS_LIMIT
    assert news.data[0].id == "29"

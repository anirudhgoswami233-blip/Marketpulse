from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
import respx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.cache import MemoryCache
from app.core.errors import ProviderError
from app.models import PriceBar, Symbol
from app.providers.base import Bar, Interval, NewsItem, SymbolRecord
from app.services import history_service, news_service, search_service, stock_service, symbol_directory
from app.services.stock_service import ChartRange
from tests.fakes import FakeProvider, daily_bar, news_item

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


async def test_news_is_classified_with_reaction(
    session_factory: async_sessionmaker[AsyncSession], aapl: Symbol
) -> None:
    provider, cache = FakeProvider(), MemoryCache()
    # Close jumps 100 -> 110 on Fri 16th, the session after the Thu 15th headline.
    days = weekdays(date(2026, 10, 16), 6)
    provider.bars = lambda *_: [daily_bar(d, close="110" if d == date(2026, 10, 16) else "100") for d in days]
    provider.news = [
        NewsItem(
            id="earn",
            headline="Apple beats estimates on record iPhone revenue",
            summary="",
            source="s",
            url="u",
            image_url=None,
            published_at=datetime(2026, 10, 15, 21, 0, tzinfo=UTC),
            category=None,
            related_symbols=[],
        ),
        NewsItem(
            id="today",  # published today: no completed following session yet
            headline="Apple names new retail chief",
            summary="",
            source="s",
            url="u",
            image_url=None,
            published_at=datetime(2026, 10, 19, 12, 0, tzinfo=UTC),
            category=None,
            related_symbols=[],
        ),
    ]
    async with session_factory() as session:
        out = await news_service.get_stock_news(session, provider, provider, cache, aapl, MON_MIDDAY)

    by_id = {item.id: item for item in out.data}
    earn = by_id["earn"]
    assert earn.impact.category == "earnings"
    assert earn.impact.materiality == "high"
    assert earn.reaction is not None
    assert earn.reaction.move_pct == Decimal("10.00")

    today_item = by_id["today"]
    assert today_item.impact.category == "other"
    assert today_item.reaction is None


async def test_news_llm_enrichment_sets_category_and_why(
    session_factory: async_sessionmaker[AsyncSession], aapl: Symbol, respx_mock: "respx.MockRouter"
) -> None:
    import json

    import httpx

    from app.core.llm import ANTHROPIC_URL, LLMClient

    provider, cache = FakeProvider(), MemoryCache()
    provider.bars = lambda *_: []  # no reaction bars; focus on the classification merge
    provider.news = [news_item("Apple opens a new store", 0)]  # keyword classifier -> other/low
    respx_mock.post(ANTHROPIC_URL).respond(
        json={
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        [{"category": "earnings", "materiality": "high", "why": "Record quarterly revenue"}]
                    ),
                }
            ]
        }
    )
    llm = LLMClient(httpx.AsyncClient(), "k", "claude-haiku-5-5")
    async with session_factory() as session:
        out = await news_service.get_stock_news(session, provider, provider, cache, aapl, MON_MIDDAY, llm=llm)

    item = out.data[0]
    assert item.impact.category == "earnings" and item.impact.materiality == "high"
    assert item.impact.why == "Record quarterly revenue"


async def test_news_reactions_best_effort_when_history_unavailable(
    session_factory: async_sessionmaker[AsyncSession], aapl: Symbol
) -> None:
    provider, cache = FakeProvider(), MemoryCache()
    provider.bars = ProviderError("fake", "no history")
    provider.news = [news_item("Apple beats estimates", 0)]
    async with session_factory() as session:
        out = await news_service.get_stock_news(session, provider, provider, cache, aapl, MON_MIDDAY)
    assert out.data[0].impact.category == "earnings"
    assert out.data[0].reaction is None  # classification still works; reaction just omitted

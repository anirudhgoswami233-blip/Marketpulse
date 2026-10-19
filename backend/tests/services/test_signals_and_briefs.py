from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal as D

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.cache import MemoryCache
from app.core.errors import ProviderUnavailable
from app.jobs import signal_outcomes
from app.models import Brief, BriefSignal, PriceBar, SignalOutcome, SignalRecord, User
from app.services import auth_service, brief_service, signal_service, symbol_directory, watchlist_service
from app.services.brief_service import TemplateWriter
from app.services.markets_service import OverviewSnapshot, save_snapshot
from app.services.search_service import resolve_symbol
from app.services.signal_service import SignalsUnavailable
from app.signals.engine import DISCLAIMER, ENGINE_VERSION
from tests.api_helpers import make_settings
from tests.fakes import FakeProvider, make_quote, news_item, trending_daily_bars
from tests.services.test_search_and_quotes import rec

SETTINGS = make_settings()
# Tue 2026-10-20 15:00 UTC = 11:00 New York (market open): last completed session is Mon 19th.
NOW = datetime(2026, 10, 20, 15, 0, tzinfo=UTC)
LAST_SESSION = date(2026, 10, 19)


@pytest.fixture
async def seeded(session_factory: async_sessionmaker[AsyncSession]) -> int:
    async with session_factory() as session:
        await symbol_directory.upsert_exchanges(session, symbol_directory.load_exchange_rows())
        await symbol_directory.upsert_symbols(
            session, "US", [rec("AAPL", "APPLE INC"), rec("MSFT", "MICROSOFT"), rec("NVDA", "NVIDIA")]
        )
        await symbol_directory.upsert_symbols(session, "L", [rec("VOD", "VODAFONE")])
        user = await auth_service.register(
            session, SETTINGS, "alice@example.com", "password123", "Alice", "Asia/Kolkata"
        )
        await session.commit()
        return user.id


def history_provider(sessions: int = 260) -> FakeProvider:
    provider = FakeProvider()
    provider.bars = lambda *_: trending_daily_bars(LAST_SESSION, sessions)
    provider.news = [
        news_item(h, i) for i, h in enumerate(["Apple beats estimates", "Shares surge", "Analysts upgrade"])
    ]
    return provider


async def test_signal_is_computed_once_per_trading_day_and_stored(
    session_factory: async_sessionmaker[AsyncSession], seeded: int
) -> None:
    provider = history_provider()
    async with session_factory() as session:
        aapl = await resolve_symbol(session, "AAPL")
        first = await signal_service.get_or_compute(session, provider, provider, MemoryCache(), aapl, NOW)
        again = await signal_service.get_or_compute(session, provider, provider, MemoryCache(), aapl, NOW)
        count = (await session.execute(select(func.count()).select_from(SignalRecord))).scalar_one()

    assert first.id == again.id and count == 1
    assert first.signal_date == LAST_SESSION and first.engine_version == ENGINE_VERSION
    assert first.label == "Bullish signals" and first.reasons
    assert any("News tone positive" in r["reason"] for r in first.reasons)
    assert first.price_at_signal == D("229.50")  # 100 + 259 * 0.5
    assert provider.news_calls == 1


async def test_news_failure_is_skipped_not_fatal(
    session_factory: async_sessionmaker[AsyncSession], seeded: int
) -> None:
    provider = history_provider()
    provider.news_error = ProviderUnavailable("fake", "down")
    async with session_factory() as session:
        record = await signal_service.get_or_compute(
            session, provider, provider, MemoryCache(), await resolve_symbol(session, "AAPL"), NOW
        )
    assert any(s["rule"] == "news" for s in record.skipped)


async def test_signals_need_price_history(
    session_factory: async_sessionmaker[AsyncSession], seeded: int
) -> None:
    provider = history_provider()
    async with session_factory() as session:
        with pytest.raises(SignalsUnavailable):
            await signal_service.get_or_compute(
                session, provider, provider, MemoryCache(), await resolve_symbol(session, "VOD"), NOW
            )
        provider.bars = ProviderUnavailable("fake", "plan")
        with pytest.raises(SignalsUnavailable):
            await signal_service.get_or_compute(
                session, provider, provider, MemoryCache(), await resolve_symbol(session, "MSFT"), NOW
            )


def make_user(tz: str, brief_time: time = time(7, 30)) -> User:
    return User(
        email="x@example.com", password_hash="x", display_name="X", timezone=tz, brief_time=brief_time
    )


@pytest.mark.parametrize(
    ("tz", "now", "due"),
    [
        ("Asia/Kolkata", datetime(2026, 10, 20, 2, 0, tzinfo=UTC), True),  # 07:30 IST exactly
        ("Asia/Kolkata", datetime(2026, 10, 20, 1, 59, tzinfo=UTC), False),  # 07:29 IST
        ("America/New_York", datetime(2026, 10, 20, 10, 0, tzinfo=UTC), False),  # 06:00 EDT, before 07:30
        ("America/New_York", datetime(2026, 10, 20, 11, 30, tzinfo=UTC), True),  # 07:30 EDT
        ("Asia/Kolkata", datetime(2026, 10, 24, 6, 0, tzinfo=UTC), False),  # Saturday
    ],
)
def test_briefs_are_due_at_the_users_local_time(tz: str, now: datetime, due: bool) -> None:
    assert brief_service.is_due(make_user(tz), now, has_brief_today=False) is due
    assert brief_service.is_due(make_user(tz), now, has_brief_today=True) is False


async def test_brief_symbols_watchlist_first_then_trending(
    session_factory: async_sessionmaker[AsyncSession], seeded: int
) -> None:
    cache = MemoryCache()
    await save_snapshot(
        cache,
        OverviewSnapshot(
            quotes={
                "NVDA": make_quote("NVDA", "500", "4.0"),
                "AAPL": make_quote("AAPL", "250", "-3.0"),
                "MSFT": make_quote("MSFT", "400", "0.1"),
            },
            updated_at=NOW,
        ),
    )
    async with session_factory() as session:
        (default,) = await watchlist_service.list_watchlists(session, seeded)
        await watchlist_service.add_symbol(session, SETTINGS, seeded, default.watchlist.id, "AAPL")
        await watchlist_service.add_symbol(session, SETTINGS, seeded, default.watchlist.id, "VOD")
        user = await session.get(User, seeded)
        assert user is not None
        entries = await brief_service.brief_symbols(session, cache, user)

    sources = [(e.symbol.symbol, e.source) for e in entries]
    assert sources[0] == ("AAPL", "watchlist")
    assert ("VOD", "watchlist") not in sources  # no price history on our plan
    assert ("NVDA", "trending") in sources and ("AAPL", "trending") not in sources  # no duplicates


async def test_build_brief_stores_items_and_replaces_same_day(
    session_factory: async_sessionmaker[AsyncSession], seeded: int
) -> None:
    provider, cache = history_provider(), MemoryCache()
    async with session_factory() as session:
        aapl = await resolve_symbol(session, "AAPL")
        msft = await resolve_symbol(session, "MSFT")
        record = await signal_service.get_or_compute(session, provider, provider, cache, aapl, NOW)
        user = await session.get(User, seeded)
        assert user is not None
        entries = [brief_service.BriefSymbol(aapl, "watchlist"), brief_service.BriefSymbol(msft, "trending")]
        for _ in range(2):
            brief = await brief_service.build_brief(
                session, cache, TemplateWriter(), user, entries, {aapl.id: record}, NOW
            )
        briefs = (await session.execute(select(Brief))).scalars().all()
        links = (await session.execute(select(BriefSignal))).scalars().all()

    assert len(briefs) == 1 and brief.brief_date == date(2026, 10, 20)  # 20:30 IST on the 20th
    assert [(link.signal_id, link.source) for link in links] == [(record.id, "watchlist")]
    assert brief.overnight["unavailable"] == ["MSFT"]
    assert DISCLAIMER in brief.summary_md and "APPLE INC" in brief.summary_md


async def test_outcomes_are_recorded_from_stored_bars(
    session_factory: async_sessionmaker[AsyncSession], seeded: int
) -> None:
    provider = history_provider()
    async with session_factory() as session:
        aapl = await resolve_symbol(session, "AAPL")
        record = await signal_service.get_or_compute(session, provider, provider, MemoryCache(), aapl, NOW)
        # Five more sessions of bars after the signal day.
        for i, day in enumerate([date(2026, 10, d) for d in (20, 21, 22, 23, 26)], start=1):
            close = record.price_at_signal + i  # type: ignore[operator]
            session.add(
                PriceBar(
                    symbol_id=aapl.id,
                    date=day,
                    open=close,
                    high=close,
                    low=close,
                    close=close,
                    volume=1,
                    source="t",
                )
            )
        await session.commit()

        stored = await signal_outcomes.evaluate_outcomes(session, None, NOW + timedelta(days=7))
        outcomes = {o.horizon_days: o for o in (await session.execute(select(SignalOutcome))).scalars()}
        again = await signal_outcomes.evaluate_outcomes(session, None, NOW + timedelta(days=7))

    assert stored == 2 and set(outcomes) == {1, 5}  # 20-day horizon not reached yet
    assert outcomes[5].outcome_date == date(2026, 10, 26)
    assert outcomes[1].return_pct == (D(1) / D("229.5") * 100).quantize(D("0.000001"))
    assert again == 0

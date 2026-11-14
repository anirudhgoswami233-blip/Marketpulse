from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

import app.models  # noqa: F401
from app.container import Container, build_container
from app.core.cache import MemoryCache
from app.core.ratelimit import Priority
from app.jobs import screener_snapshot
from app.models import SignalRecord, Symbol
from app.providers.base import Interval
from app.services import markets_service, screener_service
from app.services.markets_service import OverviewSnapshot
from app.signals.engine import ENGINE_VERSION
from tests.api_helpers import file_db, make_settings, prepare
from tests.fakes import NOW, FakeProvider, make_metrics, make_profile, make_quote, trending_daily_bars


@pytest.fixture
async def container(tmp_path: Path) -> AsyncIterator[Container]:
    built = build_container(make_settings(database_url=file_db(tmp_path)))
    yield built
    await built.close()


@pytest.fixture
async def provider(container: Container) -> FakeProvider:
    fake = FakeProvider()
    await prepare(container, fake)
    return fake


def test_week52_position() -> None:
    position = screener_service.week52_position_pct
    assert position(Decimal("100"), Decimal("80"), Decimal("120")) == Decimal("50.0")
    assert position(Decimal("130"), Decimal("80"), Decimal("120")) == Decimal("100")  # clamped
    assert position(Decimal("100"), Decimal("120"), Decimal("120")) is None  # no range
    assert position(None, Decimal("80"), Decimal("120")) is None


def test_needs_refresh_after_a_day() -> None:
    snapshot = screener_service.FundamentalsSnapshot()
    assert screener_service.needs_refresh(snapshot, NOW)
    snapshot.completed_at = NOW - timedelta(hours=23)
    assert not screener_service.needs_refresh(snapshot, NOW)
    snapshot.completed_at = NOW - timedelta(hours=25)
    assert screener_service.needs_refresh(snapshot, NOW)


async def test_refresh_runs_at_background_priority_and_keeps_partial_rows() -> None:
    provider, cache = FakeProvider(), MemoryCache()
    provider.profiles["AAPL"] = make_profile("AAPL", "Apple Inc")
    provider.metrics["AAPL"] = make_metrics("AAPL")
    provider.metrics["MSFT"] = make_metrics("MSFT", pe="35")  # metrics only: no profile on file

    snapshot = await screener_service.refresh_fundamentals(provider, cache, ["AAPL", "MSFT", "NOPE"])

    assert set(snapshot.rows) == {"AAPL", "MSFT"}
    assert snapshot.rows["AAPL"].industry == "Technology"
    assert snapshot.rows["MSFT"].name is None and snapshot.rows["MSFT"].pe_ttm == Decimal("35")
    assert snapshot.completed_at is not None
    assert {priority for _, _, priority in provider.reference_calls} == {Priority.BACKGROUND}
    assert (await screener_service.load_fundamentals(cache)).rows.keys() == snapshot.rows.keys()


async def test_screener_merges_quotes_fundamentals_and_latest_signal(
    container: Container, provider: FakeProvider
) -> None:
    provider.profiles["AAPL"] = make_profile("AAPL", "Apple Inc", market_cap="5000")
    provider.metrics["AAPL"] = make_metrics("AAPL", low="80", high="120")
    await screener_service.refresh_fundamentals(provider, container.cache, ["AAPL"])
    await markets_service.save_snapshot(
        container.cache,
        OverviewSnapshot(
            quotes={"AAPL": make_quote("AAPL", "110", "1.5")}, updated_at=NOW, stale={"AAPL": True}
        ),
    )
    async with container.session_factory() as session:
        aapl = (await session.scalars(select(Symbol).where(Symbol.symbol == "AAPL"))).one()
        for day, label, score in [
            (date(2026, 10, 15), "Neutral", 5),
            (date(2026, 10, 16), "Bullish signals", 42),
        ]:
            session.add(
                SignalRecord(
                    symbol_id=aapl.id, signal_date=day, engine_version=ENGINE_VERSION, score=score,
                    label=label,
                    reasons=[], skipped=[], indicators={}, price_at_signal=Decimal("100"), currency="USD",
                )
            )  # fmt: skip
        await session.commit()
        out = await screener_service.get_screener(session, container.cache, NOW)

    rows = {row.symbol: row for row in out.rows}
    # Only universe symbols that are in the directory are listed (the test DB seeds AAPL and MSFT).
    assert set(rows) == {"AAPL", "MSFT"}
    aapl_row = rows["AAPL"]
    assert aapl_row.name == "Apple Inc" and aapl_row.market_cap == Decimal("5000")
    assert aapl_row.price == Decimal("110") and aapl_row.week52_position_pct == Decimal("75.0")
    assert (aapl_row.signal_label, aapl_row.signal_score) == ("Bullish signals", 42)  # the newest one
    msft = rows["MSFT"]
    assert msft.name == "MICROSOFT CORP" and msft.price is None and msft.signal_label is None
    assert out.pending_fundamentals == 1 and out.stale is True and out.quotes_as_of == NOW


async def test_old_signals_are_not_shown(container: Container, provider: FakeProvider) -> None:
    async with container.session_factory() as session:
        aapl = (await session.scalars(select(Symbol).where(Symbol.symbol == "AAPL"))).one()
        session.add(
            SignalRecord(
                symbol_id=aapl.id, signal_date=date(2026, 9, 1), engine_version=ENGINE_VERSION, score=60,
                label="Bullish signals", reasons=[], skipped=[], indicators={}, price_at_signal=None,
                currency="USD",
            )
        )  # fmt: skip
        await session.commit()
        out = await screener_service.get_screener(session, container.cache, NOW)
    assert next(r for r in out.rows if r.symbol == "AAPL").signal_label is None


async def test_job_computes_a_signal_per_listed_symbol_and_is_idempotent(
    container: Container, provider: FakeProvider
) -> None:
    provider.bars = lambda symbol, interval, size: trending_daily_bars(date(2026, 10, 16), 260)
    now = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)

    assert await screener_snapshot.refresh_signals(container, now) == 2  # AAPL and MSFT are seeded
    history_calls = [c for c in provider.bars_calls if c[1] is Interval.DAY_1]
    assert {c[0] for c in history_calls} == {"AAPL", "MSFT"}

    assert await screener_snapshot.refresh_signals(container, now) == 2
    assert len([c for c in provider.bars_calls if c[1] is Interval.DAY_1]) == len(history_calls)  # no refetch


async def test_job_stops_after_repeated_history_failures(
    container: Container, provider: FakeProvider
) -> None:
    from app.core.errors import RateLimitExceeded

    provider.bars = RateLimitExceeded("fake", "slow down")
    assert await screener_snapshot.refresh_signals(container, NOW) == 0
    assert len(provider.bars_calls) <= screener_snapshot.MAX_CONSECUTIVE_SIGNAL_FAILURES

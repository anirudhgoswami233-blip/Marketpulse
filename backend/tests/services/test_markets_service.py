from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.core.cache import MemoryCache
from app.core.errors import RateLimitExceeded
from app.core.ratelimit import Priority
from app.services import markets_service
from app.services.markets_service import OverviewSnapshot, load_snapshot, save_snapshot
from app.services.reference_data import IndexProxy, OverviewConfig, RegionConfig, SectorConfig
from tests.fakes import FakeProvider, make_quote, open_us_status

CONFIG = OverviewConfig(
    regions=(
        RegionConfig("Americas", ("US",), (IndexProxy("SPY", "S&P 500", "S&P 500"),)),
        RegionConfig("India", ("NS",), (IndexProxy("INDA", "India", "MSCI India"),)),
    ),
    sectors=(SectorConfig("XLK", "Technology"),),
    movers_universe=("AAA", "BBB", "CCC", "DDD"),
)
MON_10AM_NY = datetime(2026, 10, 19, 14, 0, tzinfo=UTC)


def test_rank_movers_splits_and_orders() -> None:
    quotes = [
        make_quote("AAA", "10", "3.5"),
        make_quote("BBB", "10", "-2"),
        make_quote("CCC", "10", "0.5"),
        make_quote("DDD", "10", "-7"),
        make_quote("EEE", "10", None),
    ]
    gainers, losers = markets_service.rank_movers(quotes, count=5)
    assert [m.symbol for m in gainers] == ["AAA", "CCC"]
    assert [m.symbol for m in losers] == ["DDD", "BBB"]


async def test_overview_composes_snapshot_and_counts_pending() -> None:
    cache, provider = MemoryCache(), FakeProvider()
    snapshot = OverviewSnapshot(
        quotes={
            "SPY": make_quote("SPY", "600", "1.2"),
            "AAA": make_quote("AAA", "10", "4"),
            "XLK": make_quote("XLK", "250", "-0.8"),
        },
        updated_at=MON_10AM_NY - timedelta(minutes=2),
    )
    await save_snapshot(cache, snapshot)

    overview = await markets_service.get_overview(provider, cache, MON_10AM_NY, timedelta(minutes=15), CONFIG)

    americas, india = overview.regions
    assert americas.indices[0].quote is not None and americas.indices[0].is_etf_proxy
    assert india.indices[0].quote is None
    assert americas.markets[0].is_open and americas.markets[0].status_source == "schedule"
    assert not india.markets[0].is_open  # 19:30 IST
    assert overview.sectors[0].change_pct == Decimal("-0.8")
    assert [m.symbol for m in overview.gainers] == ["AAA"]
    assert overview.pending_symbols == 4  # INDA, BBB, CCC, DDD
    assert not overview.stale


async def test_overview_is_stale_when_snapshot_old_during_market_hours() -> None:
    cache, provider = MemoryCache(), FakeProvider()
    await save_snapshot(cache, OverviewSnapshot(updated_at=MON_10AM_NY - timedelta(hours=1)))
    overview = await markets_service.get_overview(provider, cache, MON_10AM_NY, timedelta(minutes=15), CONFIG)
    assert overview.stale


async def test_us_status_prefers_provider() -> None:
    provider = FakeProvider()
    status = open_us_status().model_copy(update={"is_open": False, "holiday": "Thanksgiving"})
    provider.status = status
    (us,) = await markets_service.market_statuses(provider, MON_10AM_NY, ["US"])
    assert us.status_source == "provider"
    assert us.is_open is False and us.holiday == "Thanksgiving"


async def test_refresh_uses_background_priority_and_survives_failures() -> None:
    cache, provider = MemoryCache(), FakeProvider()
    for symbol in CONFIG.all_symbols():
        provider.quotes[symbol] = make_quote(symbol, "10", "1")
    provider.quote_errors["BBB"] = RateLimitExceeded("fake", "429")

    snapshot = await markets_service.refresh_snapshot(provider, cache, {"SPY": "USD"}, CONFIG)

    assert set(snapshot.quotes) == set(CONFIG.all_symbols()) - {"BBB"}
    assert snapshot.quotes["SPY"].currency == "USD"
    assert snapshot.completed_at is not None
    assert set(provider.quote_priorities) == {Priority.BACKGROUND}
    assert (await load_snapshot(cache)).completed_at == snapshot.completed_at


async def test_should_refresh_skips_when_closed_and_post_close_snapshot_exists() -> None:
    cache, provider = MemoryCache(), FakeProvider()
    sunday = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
    assert await markets_service.should_refresh(provider, cache, sunday, timedelta(minutes=30))  # nothing yet

    friday_after_close = datetime(2026, 10, 16, 21, 0, tzinfo=UTC)
    await save_snapshot(cache, OverviewSnapshot(completed_at=friday_after_close))
    assert not await markets_service.should_refresh(provider, cache, sunday, timedelta(days=7))

    await save_snapshot(cache, OverviewSnapshot(completed_at=datetime(2026, 10, 16, 19, 0, tzinfo=UTC)))
    assert await markets_service.should_refresh(provider, cache, sunday, timedelta(days=7))  # pre-close data

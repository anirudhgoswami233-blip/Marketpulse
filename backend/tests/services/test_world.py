from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

import pytest

from app.core.cache import MemoryCache
from app.core.errors import ProviderUnavailable
from app.core.ratelimit import Priority
from app.providers.base import MacroObservation
from app.services import calendar_service, forex_service, fx_math, macro_service
from app.services.forex_service import FxSnapshot, StoredPair
from app.services.fx_math import PairQuote
from app.services.reference_data import BoardEntry, ForexConfig
from tests.fakes import FakeMacro, FakeProvider, make_quote

WED_NOON = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
SATURDAY = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)

QUOTES = {
    "EUR/USD": PairQuote(D("1.10"), D("1.00")),
    "USD/INR": PairQuote(D("80"), D("80")),
    "USD/JPY": PairQuote(D("150"), D("150")),
    "XAU/USD": PairQuote(D("4000"), D("4000")),
}


def test_crosses_are_derived_from_usd_pairs() -> None:
    values = fx_math.usd_values(QUOTES)
    eur_inr = fx_math.cross("EUR/INR", values)
    assert eur_inr is not None and eur_inr.rate == D("88.00000000")
    assert eur_inr.change_pct == D("10.0000")  # EUR rose 10% vs USD, INR flat
    jpy_inr = fx_math.cross("JPY/INR", values)
    assert jpy_inr is not None and jpy_inr.rate == D("0.53333333")
    assert fx_math.cross("XAU/INR", values) is not None
    assert fx_math.cross("GBP/INR", values) is None  # GBP not fetched
    assert fx_math.convert(D("100"), "EUR", "INR", values) == D("8800.00000000")
    assert fx_math.convert(D("1"), "XAU", "EUR", values) == D("3636.36363636")


def test_split_pair_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        fx_math.split_pair("EURUSD")


def test_refresh_schedule_follows_forex_hours() -> None:
    hour = timedelta(hours=1)
    assert forex_service.needs_refresh(FxSnapshot(), WED_NOON, hour)
    fresh = FxSnapshot(completed_at=WED_NOON - timedelta(minutes=20))
    assert not forex_service.needs_refresh(fresh, WED_NOON, hour)
    assert forex_service.needs_refresh(FxSnapshot(completed_at=WED_NOON - hour), WED_NOON, hour)
    # Weekend: one snapshot after Friday's 17:00 New York close (21:00 UTC) is enough.
    after_close = FxSnapshot(completed_at=datetime(2026, 10, 23, 21, 30, tzinfo=UTC))
    before_close = FxSnapshot(completed_at=datetime(2026, 10, 23, 20, 30, tzinfo=UTC))
    assert not forex_service.needs_refresh(after_close, SATURDAY, hour)
    assert forex_service.needs_refresh(before_close, SATURDAY, hour)


CONFIG = ForexConfig(
    base_pairs=("EUR/USD", "USD/INR", "GBP/USD"),
    board=(
        BoardEntry("EUR/USD", "Majors", "OANDA:EUR_USD"),
        BoardEntry("EUR/INR", "Indian rupee", "FX:EUR_INR"),
        BoardEntry("GBP/USD", "Majors", "OANDA:GBP_USD"),
    ),
    currencies=(("USD", "US dollar"), ("EUR", "Euro"), ("INR", "Indian rupee")),
    extra_pairs=(),
)


async def test_refresh_fetches_base_pairs_at_background_priority() -> None:
    provider, cache = FakeProvider(), MemoryCache()
    provider.quotes["EUR/USD"] = make_quote("EUR/USD", "1.10", prev_close="1.00")
    provider.quotes["USD/INR"] = make_quote("USD/INR", "80", prev_close="80")
    # GBP/USD has no quote: skipped, not fatal.
    snapshot = await forex_service.refresh(provider, cache, CONFIG)
    assert set(snapshot.pairs) == {"EUR/USD", "USD/INR"}
    assert set(provider.quote_priorities) == {Priority.BACKGROUND}
    assert (await forex_service.load_snapshot(cache)).completed_at == snapshot.completed_at

    board = forex_service.build_board(snapshot, WED_NOON, timedelta(hours=1), refreshing=False, config=CONFIG)
    rows = {r.pair: r for r in board.rows}
    assert rows["EUR/INR"].derived and rows["EUR/INR"].rate == D("88.00000000")
    assert not rows["EUR/USD"].derived
    assert rows["GBP/USD"].rate is None  # missing base pair shows as unavailable
    assert board.usd_per_unit["INR"] == D(1) / D(80)


def test_board_is_stale_when_old_during_trading_hours() -> None:
    old = FxSnapshot(
        pairs={
            "EUR/USD": StoredPair(
                rate=D("1.1"), prev_close=D("1.1"), fetched_at=WED_NOON - timedelta(hours=3)
            )
        },
        completed_at=WED_NOON - timedelta(hours=3),
    )
    assert forex_service.build_board(old, WED_NOON, timedelta(hours=1), False, CONFIG).stale
    assert not forex_service.build_board(old, SATURDAY, timedelta(hours=1), False, CONFIG).stale


def test_year_over_year() -> None:
    obs = [MacroObservation(date=date(2025, m, 1), value=D("100")) for m in range(1, 13)]
    obs += [
        MacroObservation(date=date(2026, 1, 1), value=D("103")),
        MacroObservation(date=date(2026, 2, 1), value=D("102.5")),
    ]
    yoy = macro_service.year_over_year(obs)
    assert [(o.date, o.value) for o in yoy] == [(date(2026, 1, 1), D("3.00")), (date(2026, 2, 1), D("2.50"))]


async def test_macro_dashboard_keeps_working_when_one_series_fails() -> None:
    series = {
        "FEDFUNDS": [(date(2026, 8, 1), "4.00"), (date(2026, 9, 1), "3.75")],
        "CPIAUCSL": [(date(2025, 9, 1), "300"), (date(2026, 9, 1), "309")],
    }
    dashboard = await macro_service.dashboard(FakeMacro(series, failing={"DGS10"}), today=date(2026, 10, 20))
    cards = {c.id: c for c in dashboard.cards}
    assert dashboard.configured
    fed = cards["FEDFUNDS"]
    assert fed.latest is not None and fed.latest.value == D("3.75") and fed.change == D("-0.25")
    cpi = cards["CPIAUCSL"]
    assert cpi.latest is not None and cpi.latest.value == D("3.00") and cpi.transform == "yoy"
    assert cards["DGS10"].error and cards["DGS10"].observations == []


async def test_macro_dashboard_reports_missing_key() -> None:
    class Unconfigured(FakeMacro):
        async def get_series(self, series_id: str, start: date):  # type: ignore[no-untyped-def]
            raise ProviderUnavailable("fred", "not configured")

    dashboard = await macro_service.dashboard(Unconfigured({}), today=date(2026, 10, 20))
    assert dashboard.configured is False and dashboard.cards == []


def test_calendar_weeks_and_surprise() -> None:
    assert calendar_service.week_bounds(date(2026, 10, 21)) == (date(2026, 10, 19), date(2026, 10, 25))
    assert calendar_service.week_bounds(date(2026, 10, 25)) == (date(2026, 10, 19), date(2026, 10, 25))
    assert calendar_service.surprise_pct(D("1.10"), D("1.00")) == D("10.0")
    assert calendar_service.surprise_pct(D("-0.5"), D("-1.0")) == D(
        "50.0"
    )  # loss narrowed: positive surprise
    assert calendar_service.surprise_pct(None, D("1")) is None
    assert calendar_service.surprise_pct(D("1"), D("0")) is None


async def test_refresh_saves_each_pair_as_it_arrives() -> None:
    provider, cache = FakeProvider(), MemoryCache()
    seen: list[set[str]] = []

    class Spy(FakeProvider):
        async def get_quote(self, symbol: str):  # type: ignore[no-untyped-def]
            seen.append(set((await forex_service.load_snapshot(cache)).pairs))
            return await provider.get_quote(symbol)

    provider.quotes["EUR/USD"] = make_quote("EUR/USD", "1.10")
    provider.quotes["USD/INR"] = make_quote("USD/INR", "80")
    await forex_service.refresh(Spy(), cache, CONFIG)
    assert seen[1] == {"EUR/USD"}  # the first pair was visible before the second was fetched


async def test_page_triggered_refresh_uses_interactive_priority() -> None:
    provider, cache = FakeProvider(), MemoryCache()
    provider.quotes["EUR/USD"] = make_quote("EUR/USD", "1.10")
    await forex_service.refresh(provider, cache, CONFIG, background=False)
    assert set(provider.quote_priorities) == {Priority.INTERACTIVE}


async def test_quotes_come_from_a_fresh_board_including_derived_crosses() -> None:
    cache = MemoryCache()
    fetched = WED_NOON - timedelta(minutes=10)
    snapshot = FxSnapshot(
        pairs={
            "EUR/USD": StoredPair(rate=D("1.10"), prev_close=D("1.00"), fetched_at=fetched),
            "USD/INR": StoredPair(rate=D("80"), prev_close=D("80"), fetched_at=fetched),
            "XAU/USD": StoredPair(rate=D("4000"), prev_close=D("3900"), fetched_at=fetched),
        },
        completed_at=fetched,
    )
    await cache.set(forex_service.SNAPSHOT_KEY, snapshot.model_dump_json(), 3600)
    hour = timedelta(hours=1)

    gold = await forex_service.quote_from_snapshot(cache, "OANDA:XAU_USD", hour, WED_NOON)
    assert (
        gold is not None
        and gold.data.price == D("4000.00000000")
        and gold.data.prev_close == D("3900.00000000")
    )
    assert gold.as_of == fetched and "board" in gold.source

    eur_inr = await forex_service.quote_from_snapshot(cache, "FX:EUR_INR", hour, WED_NOON)
    assert eur_inr is not None and eur_inr.data.price == D("88.00000000")
    assert eur_inr.data.change_pct == D("10.0000")

    assert (
        await forex_service.quote_from_snapshot(cache, "OANDA:GBP_USD", hour, WED_NOON) is None
    )  # not on board
    assert (
        await forex_service.quote_from_snapshot(cache, "OANDA:XAU_USD", timedelta(minutes=5), WED_NOON)
        is None
    )
    assert await forex_service.quote_from_snapshot(cache, "AAPL", hour, WED_NOON) is None
    assert forex_service.pair_for("FX:USD_INR") == "USD/INR"


async def test_page_triggered_refresh_finishes_at_background_priority_when_the_minute_is_spent() -> None:
    from app.core.errors import RateLimitExceeded

    provider, cache = FakeProvider(), MemoryCache()
    for pair in CONFIG.base_pairs:
        provider.quotes[pair] = make_quote(pair, "2")

    class Budgeted(FakeProvider):
        """Allows two interactive calls, then refuses interactive ones like an exhausted limiter."""

        async def get_quote(self, symbol: str):  # type: ignore[no-untyped-def]
            from app.core.ratelimit import current_priority

            if current_priority() is Priority.INTERACTIVE and len(provider.quote_priorities) >= 2:
                raise RateLimitExceeded("fake", "limiter queue wait would exceed 30s")
            return await provider.get_quote(symbol)

    snapshot = await forex_service.refresh(Budgeted(), cache, CONFIG, background=False)
    assert set(snapshot.pairs) == set(CONFIG.base_pairs)  # nothing skipped
    assert provider.quote_priorities == [Priority.INTERACTIVE, Priority.INTERACTIVE, Priority.BACKGROUND]

from datetime import date
from decimal import Decimal as D

from app.jobs.templates.brief import BriefItem, RegionMove, render
from app.signals.engine import DISCLAIMER, Label
from app.signals.performance import MIN_SAMPLE, outcome_for, summarize

AFTER = [(date(2026, 10, 20), D("102")), (date(2026, 10, 21), D("99")), (date(2026, 10, 22), D("110"))]


def test_outcome_uses_the_nth_session_after_the_signal() -> None:
    one = outcome_for(D("100"), AFTER, 1)
    assert one is not None and one.return_pct == D("2.000000") and one.outcome_date == date(2026, 10, 20)
    three = outcome_for(D("100"), AFTER, 3)
    assert three is not None and three.return_pct == D("10.000000")
    assert outcome_for(D("100"), AFTER, 5) is None  # not enough sessions yet
    assert outcome_for(D("0"), AFTER, 1) is None


def test_summary_hit_rates_by_label() -> None:
    rows = [
        (Label.BULLISH.value, 1, D("2")),
        (Label.BULLISH.value, 1, D("-1")),
        (Label.BULLISH.value, 1, D("3")),
        (Label.BEARISH.value, 1, D("-4")),
        (Label.NEUTRAL.value, 1, D("1")),
    ]
    stats = {(s.label, s.horizon_days): s for s in summarize(rows)}
    bull = stats[(Label.BULLISH.value, 1)]
    assert bull.count == 3 and bull.avg_return_pct == D("1.33") and bull.hit_rate_pct == D("66.7")
    assert not bull.enough_data and MIN_SAMPLE > 3
    assert stats[(Label.BEARISH.value, 1)].hit_rate_pct == D("100.0")  # a fall is a "hit" for bearish
    assert stats[(Label.NEUTRAL.value, 1)].hit_rate_pct is None
    empty = stats[(Label.BULLISH.value, 20)]
    assert empty.count == 0 and empty.avg_return_pct is None


def test_template_brief_has_reasons_and_disclaimer_and_no_commands() -> None:
    text = render(
        "Alice",
        date(2026, 10, 20),
        [RegionMove("Americas", 0.8, "SPY +0.80%"), RegionMove("Asia-Pacific", -1.2, "EWJ -1.20%")],
        [
            BriefItem("AAPL", "APPLE INC", "watchlist", Label.BULLISH.value, 45, ["RSI 28 = oversold"]),
            BriefItem("TSLA", "TESLA", "trending", Label.BEARISH.value, -40, ["Price below 200-day average"]),
        ],
        unavailable=["VOD"],
    )
    assert text.rstrip().endswith(f"_{DISCLAIMER}_")
    assert "Americas led (+0.80%) while Asia-Pacific lagged (-1.20%)" in text
    assert "**AAPL** (APPLE INC): Bullish signals (score +45). RSI 28 = oversold." in text
    assert "## Trending today" in text and "TSLA" in text
    assert "couldn't be computed today for: VOD" in text
    lowered = text.lower()
    assert " buy " not in lowered and " sell " not in lowered


def test_template_handles_an_empty_watchlist() -> None:
    text = render("Bob", date(2026, 10, 20), [], [], [])
    assert "Add symbols to a watchlist" in text
    assert "Regional market data wasn't available" in text
    assert DISCLAIMER in text

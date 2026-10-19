"""How past signals turned out. Pure functions, no I/O.

For a signal on day D at close P, the N-day outcome is the close N trading sessions later (the N-th stored
daily bar after D). A bullish label "hit" if the price rose; a bearish label hit if it fell. Neutral labels
have no hit rate. Small samples are reported as such rather than hidden.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal

from app.signals.engine import Label

HORIZONS = (1, 5, 20)
MIN_SAMPLE = 20  # below this, the UI warns that results are not meaningful yet
PCT_PLACES = Decimal("0.000001")


@dataclass(frozen=True)
class Outcome:
    horizon_days: int
    outcome_date: date
    price_after: Decimal
    return_pct: Decimal


def outcome_for(
    price_at_signal: Decimal, bars_after: Sequence[tuple[date, Decimal]], horizon_days: int
) -> Outcome | None:
    """`bars_after` are (date, close) for sessions strictly after the signal date, oldest first."""
    if horizon_days < 1 or len(bars_after) < horizon_days or price_at_signal <= 0:
        return None
    outcome_date, close = bars_after[horizon_days - 1]
    ret = ((close - price_at_signal) / price_at_signal * 100).quantize(PCT_PLACES, rounding=ROUND_HALF_EVEN)
    return Outcome(horizon_days, outcome_date, close, ret)


@dataclass(frozen=True)
class LabelStats:
    label: str
    horizon_days: int
    count: int
    avg_return_pct: Decimal | None
    hit_rate_pct: Decimal | None  # None for Neutral
    enough_data: bool


def summarize(rows: Sequence[tuple[str, int, Decimal]]) -> list[LabelStats]:
    """`rows` are (label, horizon_days, return_pct). Returns stats for every label x horizon."""
    stats: list[LabelStats] = []
    for label in Label:
        for horizon in HORIZONS:
            returns = [r for lbl, h, r in rows if lbl == label.value and h == horizon]
            count = len(returns)
            avg = (sum(returns, Decimal(0)) / count).quantize(Decimal("0.01")) if count else None
            hit: Decimal | None = None
            if count and label is not Label.NEUTRAL:
                wins = sum(1 for r in returns if (r > 0 if label is Label.BULLISH else r < 0))
                hit = (Decimal(wins) / count * 100).quantize(Decimal("0.1"))
            stats.append(LabelStats(label.value, horizon, count, avg, hit, count >= MIN_SAMPLE))
    return stats

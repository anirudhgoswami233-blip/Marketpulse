"""How a stock moved right after a news headline. Pure functions, no I/O.

For a headline published on day D, the reaction is the first trading session strictly after D versus the
last session on or before D (its reference close). This ties an observed move to the specific headline we
show, and needs only the daily bars we already store — no extra provider call. It is a *past* move, stated
as fact; it is never a forecast.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal

PCT_PLACES = Decimal("0.01")


@dataclass(frozen=True)
class NextSessionMove:
    ref_date: date  # last session on or before the headline date (reference close)
    next_date: date  # first session after the headline date
    move_pct: Decimal


def next_session_move(bars: Sequence[tuple[date, Decimal]], news_date: date) -> NextSessionMove | None:
    """`bars` are (date, close), oldest first. Returns None when a reference or following session is missing
    (e.g. the headline is from today and the next session hasn't closed yet)."""
    ref: tuple[date, Decimal] | None = None
    nxt: tuple[date, Decimal] | None = None
    for day, close in bars:
        if day <= news_date:
            ref = (day, close)
        else:
            nxt = (day, close)
            break
    if ref is None or nxt is None or ref[1] <= 0:
        return None
    move = ((nxt[1] - ref[1]) / ref[1] * 100).quantize(PCT_PLACES, rounding=ROUND_HALF_EVEN)
    return NextSessionMove(ref_date=ref[0], next_date=nxt[0], move_pct=move)

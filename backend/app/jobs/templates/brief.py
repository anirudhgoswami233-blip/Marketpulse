"""Templated Daily Brief text (used whenever no LLM is configured). Pure function, no I/O.

The brief describes indicator readings with their reasons. It never tells anyone to buy or sell, and it
always ends with the disclaimer.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from app.signals.engine import DISCLAIMER, Label


@dataclass(frozen=True)
class RegionMove:
    region: str
    avg_change_pct: float | None
    detail: str  # e.g. "SPY +0.4%, QQQ +0.9%"


@dataclass(frozen=True)
class BriefItem:
    symbol: str
    name: str
    source: str  # "watchlist" | "trending"
    label: str
    score: int
    reasons: Sequence[str]


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.2f}%"


def _overnight_sentence(moves: Sequence[RegionMove]) -> str:
    known = [m for m in moves if m.avg_change_pct is not None]
    if not known:
        return "Regional market data wasn't available for this brief."
    parts = [f"{m.region} {_pct(m.avg_change_pct)}" for m in known]
    best = max(known, key=lambda m: m.avg_change_pct or 0)
    worst = min(known, key=lambda m: m.avg_change_pct or 0)
    lead = ""
    if best is not worst:
        lead = (
            f"{best.region} led ({_pct(best.avg_change_pct)}) "
            f"while {worst.region} lagged ({_pct(worst.avg_change_pct)})."
        )
    return f"In the last session, regional ETF proxies moved: {', '.join(parts)}. {lead}".strip()


def render(
    display_name: str,
    brief_date: date,
    moves: Sequence[RegionMove],
    items: Sequence[BriefItem],
    unavailable: Sequence[str],
) -> str:
    lines = [f"# Daily Market Brief: {brief_date:%A, %d %B %Y}", "", f"Good morning, {display_name}.", ""]
    lines += ["## Overnight", "", _overnight_sentence(moves), ""]
    for m in moves:
        lines.append(f"- **{m.region}** {_pct(m.avg_change_pct)}: {m.detail}")
    lines.append("")

    for source, title in (("watchlist", "Your watchlist"), ("trending", "Trending today")):
        group = [i for i in items if i.source == source]
        lines += [f"## {title}", ""]
        if not group:
            lines += [
                "Add symbols to a watchlist to see their signals here."
                if source == "watchlist"
                else "No trending symbols today.",
                "",
            ]
            continue
        counts = {label: sum(1 for i in group if i.label == label.value) for label in Label}
        lines.append(
            f"{counts[Label.BULLISH]} with bullish signals, {counts[Label.BEARISH]} with bearish signals, "
            f"{counts[Label.NEUTRAL]} neutral."
        )
        lines.append("")
        for item in sorted(group, key=lambda i: -abs(i.score)):
            reasons = "; ".join(item.reasons) if item.reasons else "no indicator readings available"
            lines.append(
                f"- **{item.symbol}** ({item.name}): {item.label} (score {item.score:+d}). {reasons}."
            )
        lines.append("")

    if unavailable:
        lines += [f"_Signals couldn't be computed today for: {', '.join(unavailable)}._", ""]
    lines += ["---", "", f"_{DISCLAIMER}_"]
    return "\n".join(lines)

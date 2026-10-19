"""Macro dashboard from FRED: rates, inflation, labour. Each series is cached 12h by the provider."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from app.core.errors import ProviderError, ProviderUnavailable
from app.providers.base import MacroDataProvider, MacroObservation

logger = logging.getLogger(__name__)

DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "macro.json"
PCT = Decimal("0.01")


@dataclass(frozen=True)
class MacroSpec:
    id: str
    title: str
    group: str
    transform: Literal["level", "yoy"]
    unit: str


@lru_cache
def macro_specs() -> tuple[int, tuple[MacroSpec, ...]]:
    raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    return raw["lookback_years"], tuple(MacroSpec(**s) for s in raw["series"])


def year_over_year(observations: Sequence[MacroObservation]) -> list[MacroObservation]:
    """% change versus the same month a year earlier (monthly index series such as CPI). Pure."""
    by_month = {(o.date.year, o.date.month): o.value for o in observations}
    out = []
    for o in observations:
        earlier = by_month.get((o.date.year - 1, o.date.month))
        if earlier:
            out.append(MacroObservation(date=o.date, value=((o.value / earlier - 1) * 100).quantize(PCT)))
    return out


class Point(BaseModel):
    date: date
    value: Decimal


class MacroCard(BaseModel):
    id: str
    title: str
    group: str
    unit: str
    transform: str
    source_title: str | None
    frequency: str | None
    latest: Point | None
    previous: Point | None
    change: Decimal | None
    observations: list[Point]
    as_of: datetime | None
    stale: bool
    # Set when the series couldn't be loaded; the dashboard shows the rest.
    error: str | None = None


class MacroDashboard(BaseModel):
    cards: list[MacroCard]
    configured: bool


async def _card(provider: MacroDataProvider, spec: MacroSpec, start: date) -> MacroCard:
    try:
        fetched = await provider.get_series(spec.id, start)
    except ProviderUnavailable:
        raise
    except ProviderError as exc:
        logger.warning("Macro series %s failed: %s", spec.id, exc)
        return MacroCard(
            id=spec.id, title=spec.title, group=spec.group, unit=spec.unit, transform=spec.transform,
            source_title=None, frequency=None, latest=None, previous=None, change=None, observations=[],
            as_of=None, stale=False, error="This series couldn't be loaded right now.",
        )  # fmt: skip
    series = fetched.data
    observations = year_over_year(series.observations) if spec.transform == "yoy" else series.observations
    points = [Point(date=o.date, value=o.value) for o in observations]
    latest = points[-1] if points else None
    previous = points[-2] if len(points) > 1 else None
    return MacroCard(
        id=spec.id,
        title=spec.title,
        group=spec.group,
        unit=spec.unit,
        transform=spec.transform,
        source_title=series.title,
        frequency=series.frequency,
        latest=latest,
        previous=previous,
        change=(latest.value - previous.value).quantize(PCT) if latest and previous else None,
        observations=points,
        as_of=fetched.as_of,
        stale=fetched.stale,
    )


async def dashboard(provider: MacroDataProvider, today: date | None = None) -> MacroDashboard:
    today = today or datetime.now(UTC).date()
    years, specs = macro_specs()
    # One extra year so year-over-year values exist from the start of the window.
    start = date(today.year - years - 1, today.month, 1)
    try:
        cards = await asyncio.gather(*(_card(provider, spec, start) for spec in specs))
    except ProviderUnavailable:
        return MacroDashboard(cards=[], configured=False)
    window_start = date(today.year - years, today.month, 1)
    for card in cards:
        card.observations = [p for p in card.observations if p.date >= window_start]
    return MacroDashboard(cards=list(cards), configured=True)

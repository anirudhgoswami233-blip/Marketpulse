"""Static reference data from app/data: exchange schedules and the markets-overview instrument lists."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.services.market_hours import ExchangeSchedule, parse_schedule

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


@dataclass(frozen=True)
class IndexProxy:
    symbol: str
    name: str
    tracks: str


@dataclass(frozen=True)
class RegionConfig:
    region: str
    exchanges: tuple[str, ...]
    indices: tuple[IndexProxy, ...]


@dataclass(frozen=True)
class SectorConfig:
    symbol: str
    sector: str


@dataclass(frozen=True)
class OverviewConfig:
    regions: tuple[RegionConfig, ...]
    sectors: tuple[SectorConfig, ...]
    movers_universe: tuple[str, ...]

    def all_symbols(self) -> list[str]:
        """Every symbol the overview needs, in refresh priority order, without duplicates."""
        ordered = [i.symbol for r in self.regions for i in r.indices]
        ordered += [s.symbol for s in self.sectors]
        ordered += list(self.movers_universe)
        return list(dict.fromkeys(ordered))


def _load(name: str) -> Any:
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


@lru_cache
def exchange_rows() -> tuple[dict[str, Any], ...]:
    return tuple(_load("exchanges.json"))


@lru_cache
def exchange_schedules() -> dict[str, ExchangeSchedule]:
    return {row["code"]: parse_schedule(row) for row in exchange_rows()}


@lru_cache
def overview_config() -> OverviewConfig:
    raw = _load("market_overview.json")
    return OverviewConfig(
        regions=tuple(
            RegionConfig(
                region=r["region"],
                exchanges=tuple(r["exchanges"]),
                indices=tuple(IndexProxy(**i) for i in r["indices"]),
            )
            for r in raw["regions"]
        ),
        sectors=tuple(SectorConfig(**s) for s in raw["sectors"]),
        movers_universe=tuple(raw["movers_universe"]),
    )


@dataclass(frozen=True)
class BoardEntry:
    pair: str  # "EUR/USD"
    group: str
    symbol: str | None  # directory symbol for linking, if the pair is in the directory


@dataclass(frozen=True)
class ExtraPair:
    symbol: str
    display_symbol: str
    description: str


@dataclass(frozen=True)
class ForexConfig:
    base_pairs: tuple[str, ...]
    board: tuple[BoardEntry, ...]
    currencies: tuple[tuple[str, str], ...]  # (code, name)
    extra_pairs: tuple[ExtraPair, ...]
    # Asset codes our forex provider doesn't price on its free plan: code -> name.
    unpriced_assets: tuple[tuple[str, str], ...] = ()


@lru_cache
def forex_config() -> ForexConfig:
    raw = _load("forex.json")
    return ForexConfig(
        base_pairs=tuple(raw["base_pairs"]),
        board=tuple(BoardEntry(**b) for b in raw["board"]),
        currencies=tuple((c["code"], c["name"]) for c in raw["currencies"]),
        extra_pairs=tuple(ExtraPair(**p) for p in raw["extra_pairs"]),
        unpriced_assets=tuple((a["code"], a["name"]) for a in raw.get("unpriced_assets", [])),
    )

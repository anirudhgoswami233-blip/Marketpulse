from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from app.providers.base import Bar, MarketSession, Quote


class MarketStatusOut(BaseModel):
    exchange: str
    name: str
    region: str
    timezone: str
    local_time: datetime
    is_open: bool
    session: MarketSession
    holiday: str | None
    next_change_at: datetime | None
    # "provider": live status from our data provider (knows holidays); "schedule": regular hours only
    status_source: str


class IndexCard(BaseModel):
    symbol: str
    name: str
    tracks: str
    is_etf_proxy: bool = True
    quote: Quote | None


class RegionOverview(BaseModel):
    region: str
    markets: list[MarketStatusOut]
    indices: list[IndexCard]


class SectorTile(BaseModel):
    symbol: str
    sector: str
    price: Decimal | None
    change_pct: Decimal | None


class Mover(BaseModel):
    symbol: str
    price: Decimal
    change: Decimal | None
    change_pct: Decimal
    currency: str | None


class MarketOverview(BaseModel):
    regions: list[RegionOverview]
    sectors: list[SectorTile]
    gainers: list[Mover]
    losers: list[Mover]
    movers_universe_size: int
    # Overall freshness; null as_of means the first background refresh hasn't finished yet.
    as_of: datetime | None
    stale: bool
    pending_symbols: int


class SymbolOut(BaseModel):
    symbol: str
    display_symbol: str
    description: str
    exchange: str
    type: str
    currency: str | None
    price_available: bool
    streamable: bool


class SearchResults(BaseModel):
    query: str
    results: list[SymbolOut]


class ChartOut(BaseModel):
    symbol: str
    range: str
    interval: str
    currency: str | None
    timezone: str | None
    bars: list[Bar]

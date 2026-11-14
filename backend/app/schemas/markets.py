from datetime import date, datetime
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


class ScreenerRow(BaseModel):
    symbol: str
    display_symbol: str
    name: str
    industry: str | None
    currency: str | None
    price: Decimal | None
    change_pct: Decimal | None
    market_cap: Decimal | None
    pe_ttm: Decimal | None
    eps_ttm: Decimal | None
    beta: Decimal | None
    dividend_yield_pct: Decimal | None
    week52_low: Decimal | None
    week52_high: Decimal | None
    # Where the price sits in its 52-week range: 0 = at the low, 100 = at the high.
    week52_position_pct: Decimal | None
    # Latest stored technical signal, if one was computed in the last few sessions.
    signal_label: str | None
    signal_score: int | None
    signal_date: date | None


class ScreenerOut(BaseModel):
    rows: list[ScreenerRow]
    universe_size: int
    # Symbols still waiting for their first fundamentals fetch (the job fills them in over a few minutes).
    pending_fundamentals: int
    refreshing: bool
    quotes_as_of: datetime | None
    fundamentals_as_of: datetime | None
    stale: bool


class SymbolOut(BaseModel):
    symbol: str
    display_symbol: str
    description: str
    exchange: str
    type: str
    currency: str | None
    price_available: bool
    streamable: bool
    tradable: bool
    # Plain-language explanations for the UI (None when not applicable).
    price_note: str | None
    trade_note: str | None
    # Minutes of delay on quotes when there's no live stream (forex/metals), else None.
    quote_delay_min: int | None


class PeerOut(BaseModel):
    symbol: str
    display_symbol: str
    description: str


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

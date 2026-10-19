from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from app.core.cache import Fetched
from app.providers.base import Quote
from app.schemas.markets import SymbolOut


class WatchlistOut(BaseModel):
    id: int
    name: str
    created_at: datetime
    symbols: list[SymbolOut]


class WatchlistCreate(BaseModel):
    name: str = Field(max_length=200)


class WatchlistItemCreate(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)


class QuoteResult(BaseModel):
    symbol: str
    quote: Fetched[Quote] | None
    # Set when `quote` is null: "unavailable" (not on our data plan), "not_found", or "provider_error".
    error: str | None = None


class BulkQuotes(BaseModel):
    results: list[QuoteResult]


class OrderIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    side: Literal["buy", "sell"]
    # A string keeps the user's exact decimal input (no float rounding on the way in).
    quantity: Decimal


class TradeOut(BaseModel):
    id: int
    symbol: str
    display_symbol: str
    side: Literal["buy", "sell"]
    quantity: Decimal
    price: Decimal
    currency: str
    notional: Decimal
    realized_pnl: Decimal | None
    executed_at: datetime
    price_as_of: datetime


class PositionOut(BaseModel):
    symbol: str
    display_symbol: str
    description: str
    quantity: Decimal
    avg_cost: Decimal
    currency: str
    last_price: Decimal | None
    price_as_of: datetime | None
    price_stale: bool
    market_value: Decimal | None
    cost_basis: Decimal
    unrealized_pnl: Decimal | None
    unrealized_pnl_pct: Decimal | None


class PortfolioOut(BaseModel):
    id: int
    name: str
    base_currency: str
    starting_cash: Decimal
    cash: Decimal
    market_value: Decimal
    equity: Decimal
    total_return: Decimal
    total_return_pct: Decimal | None
    realized_pnl: Decimal
    positions: list[PositionOut]
    # True when some positions couldn't be priced; they're valued at cost in the totals.
    incomplete: bool
    as_of: datetime

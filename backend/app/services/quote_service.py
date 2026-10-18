"""Quotes for display: the cached REST snapshot, overlaid with the latest WebSocket trade when it's newer."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.core.cache import Fetched
from app.models import Symbol
from app.providers.base import MarketDataProvider, Quote
from app.ws.hub import PriceHub


async def get_quote(provider: MarketDataProvider, hub: PriceHub, symbol: Symbol) -> Fetched[Quote]:
    fetched = await provider.get_quote(symbol.symbol)
    quote = fetched.data.model_copy(update={"currency": symbol.currency})
    as_of = fetched.as_of

    trade = hub.last_trade(symbol.symbol)
    reference = quote.timestamp or fetched.as_of
    if trade is not None and trade.timestamp > reference:
        quote = apply_trade(quote, trade.price, trade.timestamp)
        as_of = max(as_of, trade.timestamp)
    return Fetched[Quote](data=quote, as_of=as_of, source=fetched.source, stale=fetched.stale)


def apply_trade(quote: Quote, price: Decimal, timestamp: datetime) -> Quote:
    """Move a quote to a newer trade price, recomputing change versus the previous close."""
    update: dict[str, object] = {"price": price, "timestamp": timestamp}
    if quote.prev_close:
        change = price - quote.prev_close
        update["change"] = change
        update["change_pct"] = (change / quote.prev_close * 100).quantize(Decimal("0.0001"))
    if quote.high is not None and price > quote.high:
        update["high"] = price
    if quote.low is not None and price < quote.low:
        update["low"] = price
    return quote.model_copy(update=update)

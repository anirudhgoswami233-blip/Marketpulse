"""Decides which provider serves each capability.

Routing follows docs/finnhub-endpoints.md: Finnhub for everything its free tier supports, Twelve Data
for price history and forex rates, FRED for macro. Services ask the registry for a capability and never
name a vendor, so swapping providers is a change here only.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.cache import CacheBackend
from app.providers.base import MacroDataProvider, MarketDataProvider


class UnconfiguredProvider(MarketDataProvider):
    """Stands in when a provider's API key is missing; every call raises ProviderUnavailable."""

    def __init__(self, name: str, cache: CacheBackend) -> None:
        self.name = f"{name} (not configured)"
        self.cache = cache


class UnconfiguredMacroProvider(MacroDataProvider):
    def __init__(self, name: str, cache: CacheBackend) -> None:
        self.name = f"{name} (not configured)"
        self.cache = cache


@dataclass(frozen=True)
class ProviderRegistry:
    quotes: MarketDataProvider
    reference: MarketDataProvider  # symbol search/lists, profiles, metrics
    news: MarketDataProvider
    calendars: MarketDataProvider
    market_status: MarketDataProvider
    history: MarketDataProvider
    forex_rates: MarketDataProvider
    macro: MacroDataProvider
    # Quotes for forex and metals (Finnhub's free tier has none).
    forex_quotes: MarketDataProvider | None = None

    def quotes_for(self, exchange_code: str) -> MarketDataProvider:
        """Which provider quotes a symbol on `exchange_code`. Services pass `symbol.exchange_code`."""
        if exchange_code in ("OANDA", "FX") and self.forex_quotes is not None:
            return self.forex_quotes
        return self.quotes

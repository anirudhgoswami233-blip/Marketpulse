class ProviderError(Exception):
    """A data provider call failed (network error, 5xx, malformed response, ...)."""

    def __init__(self, provider: str, message: str) -> None:
        super().__init__(f"{provider}: {message}")
        self.provider = provider
        self.message = message


class ProviderUnavailable(ProviderError):
    """The provider can't serve this request: premium-only on our plan, not configured, or not supported."""


class RateLimitExceeded(ProviderError):
    """Our limiter budget, or the vendor's own rate limit, was exhausted."""


class NoDataError(ProviderError):
    """The provider answered, but has no data for this symbol/query."""


class SymbolNotFound(LookupError):
    """The symbol isn't in our directory (search the seeded DB first)."""

    def __init__(self, symbol: str) -> None:
        super().__init__(f"unknown symbol {symbol}")
        self.symbol = symbol

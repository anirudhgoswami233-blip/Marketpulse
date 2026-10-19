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


class AppError(Exception):
    """A user-facing domain error. The API returns `{detail, code}` with `status`.

    `message` is shown to users as-is, so keep it friendly and free of internals.
    """

    status: int = 400
    code: str = "bad_request"

    def __init__(self, message: str, *, code: str | None = None, status: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if status is not None:
            self.status = status


class NotFound(AppError):
    status, code = 404, "not_found"


class Conflict(AppError):
    status, code = 409, "conflict"


class Unauthorized(AppError):
    status, code = 401, "unauthorized"


class TooManyRequests(AppError):
    status, code = 429, "too_many_requests"


class ValidationFailed(AppError):
    status, code = 422, "invalid"

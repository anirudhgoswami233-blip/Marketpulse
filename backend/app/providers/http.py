"""Rate-limited HTTP transport shared by provider adapters.

Every request takes a limiter slot first (retries take another). Errors are mapped to our exception
types, and messages only ever include the URL path, never the query string, because FRED requires
its key as a query parameter.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

import httpx

from app.core.errors import NoDataError, ProviderError, ProviderUnavailable, RateLimitExceeded
from app.core.ratelimit import RateLimiter

logger = logging.getLogger(__name__)

DEFAULT_RETRY_AFTER_S = 2.0
MAX_RETRY_AFTER_S = 10.0


class ProviderTransport:
    def __init__(
        self,
        provider: str,
        client: httpx.AsyncClient,
        limiter: RateLimiter,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.provider = provider
        self.client = client
        self.limiter = limiter
        self._sleep = sleep

    async def get_json(
        self,
        path: str,
        params: Mapping[str, str | int] | None = None,
        *,
        follow_redirects: bool = False,
        body_error_statuses: tuple[int, ...] = (),
    ) -> Any:
        """GET and decode JSON. Statuses in `body_error_statuses` return the decoded body so the adapter
        can map the vendor's error message itself."""
        response = await self._send(path, params, follow_redirects)
        if response.status_code == 429:
            # Back off once, then give up so the caller can serve cached data.
            delay = _retry_after(response)
            logger.warning("%s 429 on %s; retrying once in %.1fs", self.provider, path, delay)
            await self._sleep(delay)
            response = await self._send(path, params, follow_redirects)
            if response.status_code == 429:
                raise RateLimitExceeded(self.provider, f"vendor rate limit on {path}")

        status = response.status_code
        if status in body_error_statuses:
            return _decode(response, self.provider, path)
        if status in (401, 403):
            raise ProviderUnavailable(self.provider, f"HTTP {status} on {path} (not available on our plan)")
        if status == 404:
            raise NoDataError(self.provider, f"HTTP 404 on {path}")
        if status >= 400:
            raise ProviderError(self.provider, f"HTTP {status} on {path}")
        return _decode(response, self.provider, path)

    async def _send(
        self, path: str, params: Mapping[str, str | int] | None, follow_redirects: bool
    ) -> httpx.Response:
        await self.limiter.acquire()
        try:
            return await self.client.get(path, params=params, follow_redirects=follow_redirects)
        except httpx.TimeoutException as exc:
            raise ProviderError(self.provider, f"timeout on {path}") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(self.provider, f"{type(exc).__name__} on {path}") from exc


def _decode(response: httpx.Response, provider: str, path: str) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        raise ProviderError(provider, f"malformed JSON from {path}") from exc


def _retry_after(response: httpx.Response) -> float:
    try:
        value = float(response.headers.get("Retry-After", DEFAULT_RETRY_AFTER_S))
    except ValueError:
        value = DEFAULT_RETRY_AFTER_S
    return min(max(value, 0.0), MAX_RETRY_AFTER_S)

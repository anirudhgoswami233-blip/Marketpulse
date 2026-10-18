"""Cache backends and the @cached decorator used by provider adapters.

Each cached value is stored twice: under a fresh key with the data's TTL, and under a stale key
that lives much longer. When the provider fails (rate limit, outage, premium-only), the decorator
serves the stale copy with `stale=True` and its original `as_of`, so pages degrade instead of breaking.
"""

from __future__ import annotations

import functools
import json
import logging
import time
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Any, Concatenate, Protocol, get_type_hints

from pydantic import BaseModel, TypeAdapter

from app.core.errors import NoDataError, ProviderError

logger = logging.getLogger(__name__)

STALE_TTL_S = 7 * 24 * 3600


class CacheBackend(Protocol):
    async def get(self, key: str) -> str | None: ...
    async def set(self, key: str, value: str, ttl_s: int) -> None: ...
    async def delete(self, key: str) -> None: ...
    async def close(self) -> None: ...


class MemoryCache:
    """In-process cache for dev when REDIS_URL is empty. Not shared between processes."""

    def __init__(self, clock: Callable[[], float] = time.monotonic, max_entries: int = 10_000) -> None:
        self._clock = clock
        self._max_entries = max_entries
        self._data: dict[str, tuple[float, str]] = {}

    async def get(self, key: str) -> str | None:
        entry = self._data.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if self._clock() >= expires_at:
            del self._data[key]
            return None
        return value

    async def set(self, key: str, value: str, ttl_s: int) -> None:
        if len(self._data) >= self._max_entries and key not in self._data:
            self._evict()
        self._data[key] = (self._clock() + ttl_s, value)

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)

    async def close(self) -> None:
        self._data.clear()

    def _evict(self) -> None:
        now = self._clock()
        for key in [k for k, (exp, _) in self._data.items() if exp <= now]:
            del self._data[key]
        while len(self._data) >= self._max_entries:
            del self._data[min(self._data, key=lambda k: self._data[k][0])]


class RedisCache:
    def __init__(self, url: str) -> None:
        from redis.asyncio import Redis

        self._redis: Redis = Redis.from_url(url, decode_responses=True)

    async def get(self, key: str) -> str | None:
        value = await self._redis.get(key)
        return value if isinstance(value, str) else None

    async def set(self, key: str, value: str, ttl_s: int) -> None:
        await self._redis.set(key, value, ex=ttl_s)

    async def delete(self, key: str) -> None:
        await self._redis.delete(key)

    async def close(self) -> None:
        await self._redis.aclose()


def build_cache(redis_url: str) -> CacheBackend:
    return RedisCache(redis_url) if redis_url else MemoryCache()


class Fetched[T](BaseModel):
    """Provider result plus freshness metadata, so the UI can show 'data as of HH:MM'."""

    data: T
    as_of: datetime
    source: str
    stale: bool = False


class CachingProvider(Protocol):
    name: str
    cache: CacheBackend


def _cache_key(provider: str, method: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    parts = json.dumps([args, sorted(kwargs.items())], default=str, separators=(",", ":"))
    return f"mp:{provider}:{method}:{parts}"


class cached:
    """Cache an adapter method's result. The wrapped method returns `Fetched[R]` instead of `R`."""

    def __init__(self, ttl: int, stale_ttl: int = STALE_TTL_S) -> None:
        self.ttl = ttl
        self.stale_ttl = stale_ttl

    def __call__[S: CachingProvider, **P, R](
        self, func: Callable[Concatenate[S, P], Coroutine[Any, Any, R]]
    ) -> Callable[Concatenate[S, P], Coroutine[Any, Any, Fetched[R]]]:
        ttl, stale_ttl = self.ttl, self.stale_ttl
        adapter: TypeAdapter[Any] | None = None

        def get_adapter() -> TypeAdapter[Any]:
            nonlocal adapter
            if adapter is None:
                adapter = TypeAdapter(get_type_hints(func)["return"])
            return adapter

        async def wrapper(self: S, /, *args: P.args, **kwargs: P.kwargs) -> Fetched[R]:
            key = _cache_key(self.name, func.__name__, args, kwargs)
            raw = await self.cache.get(key)
            if raw is not None:
                return _decode(raw, get_adapter(), self.name, stale=False)

            try:
                data = await func(self, *args, **kwargs)
            except NoDataError:
                raise
            except ProviderError as exc:
                stale_raw = await self.cache.get(f"{key}:stale")
                if stale_raw is None:
                    raise
                logger.warning("Serving stale %s.%s after provider error: %s", self.name, func.__name__, exc)
                return _decode(stale_raw, get_adapter(), self.name, stale=True)

            as_of = datetime.now(UTC)
            payload = json.dumps(
                {"as_of": as_of.isoformat(), "data": get_adapter().dump_python(data, mode="json")}
            )
            await self.cache.set(key, payload, ttl)
            await self.cache.set(f"{key}:stale", payload, stale_ttl)
            return Fetched[R](data=data, as_of=as_of, source=self.name)

        functools.update_wrapper(wrapper, func)
        return wrapper


def _decode(raw: str, adapter: TypeAdapter[Any], source: str, *, stale: bool) -> Fetched[Any]:
    payload = json.loads(raw)
    return Fetched[Any](
        data=adapter.validate_python(payload["data"]),
        as_of=datetime.fromisoformat(payload["as_of"]),
        source=source,
        stale=stale,
    )

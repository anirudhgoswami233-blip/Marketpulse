"""Sliding-window rate limiters shared by every outbound provider call.

Callers wait in the limiter until a slot frees up, rather than failing. Background jobs (for example
the daily brief) may only use `background_share` of the per-minute budget, so interactive page loads
always have headroom. Set priority with `background_priority()` instead of passing it through every call.
"""

from __future__ import annotations

import asyncio
import contextvars
import math
import time
from collections import deque
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from app.core.errors import RateLimitExceeded


class Priority(StrEnum):
    INTERACTIVE = "interactive"
    BACKGROUND = "background"


_priority: contextvars.ContextVar[Priority] = contextvars.ContextVar(
    "limiter_priority", default=Priority.INTERACTIVE
)


@contextmanager
def background_priority() -> Iterator[None]:
    token = _priority.set(Priority.BACKGROUND)
    try:
        yield
    finally:
        _priority.reset(token)


def current_priority() -> Priority:
    return _priority.get()


@dataclass(frozen=True)
class LimiterUsage:
    name: str
    used_in_window: int
    limit_per_window: int
    window_s: float
    used_today: int | None
    daily_limit: int | None


class RateLimiter(Protocol):
    name: str

    async def acquire(self) -> None: ...
    async def usage(self) -> LimiterUsage: ...


@dataclass(frozen=True)
class LimiterConfig:
    name: str
    limit: int
    window_s: float = 60.0
    background_share: float = 0.7
    daily_limit: int | None = None
    max_wait_s: float = 30.0

    def allowed_for(self, priority: Priority) -> int:
        if priority is Priority.INTERACTIVE:
            return self.limit
        return max(1, math.floor(self.limit * self.background_share))


class MemoryRateLimiter:
    """In-process limiter for dev (REDIS_URL empty). The budget is per process."""

    def __init__(
        self,
        config: LimiterConfig,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        today: Callable[[], str] = lambda: datetime.now(UTC).date().isoformat(),
    ) -> None:
        self.name = config.name
        self._config = config
        self._clock = clock
        self._sleep = sleep
        self._today = today
        self._calls: deque[float] = deque()
        self._lock = asyncio.Lock()
        self._day = ""
        self._day_count = 0

    async def acquire(self) -> None:
        cfg = self._config
        allowed = cfg.allowed_for(current_priority())
        deadline = self._clock() + cfg.max_wait_s
        while True:
            async with self._lock:
                now = self._clock()
                self._check_daily_budget()
                while self._calls and self._calls[0] <= now - cfg.window_s:
                    self._calls.popleft()
                if len(self._calls) < allowed:
                    self._calls.append(now)
                    self._day_count += 1
                    return
                # Wait until enough old calls leave the window to bring us below `allowed`.
                wait = self._calls[len(self._calls) - allowed] + cfg.window_s - now
            if now + wait > deadline:
                raise RateLimitExceeded(cfg.name, f"limiter queue wait would exceed {cfg.max_wait_s:.0f}s")
            await self._sleep(max(wait, 0.001))

    def _check_daily_budget(self) -> None:
        today = self._today()
        if today != self._day:
            self._day, self._day_count = today, 0
        if self._config.daily_limit is not None and self._day_count >= self._config.daily_limit:
            raise RateLimitExceeded(
                self._config.name, f"daily budget of {self._config.daily_limit} calls used"
            )

    async def usage(self) -> LimiterUsage:
        now = self._clock()
        used = sum(1 for t in self._calls if t > now - self._config.window_s)
        return LimiterUsage(
            name=self.name,
            used_in_window=used,
            limit_per_window=self._config.limit,
            window_s=self._config.window_s,
            used_today=self._day_count if self._day == self._today() else 0,
            daily_limit=self._config.daily_limit,
        )


# KEYS[1]=window zset, KEYS[2]=daily counter. ARGV: window_ms, allowed, daily_limit (0 = none), member.
# Returns 0 when a slot was taken, -1 when the daily budget is spent, otherwise milliseconds to wait.
_ACQUIRE_LUA = """
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
local window = tonumber(ARGV[1])
local allowed = tonumber(ARGV[2])
local daily_limit = tonumber(ARGV[3])
if daily_limit > 0 then
  local used = tonumber(redis.call('GET', KEYS[2]) or '0')
  if used >= daily_limit then return -1 end
end
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - window)
local count = redis.call('ZCARD', KEYS[1])
if count < allowed then
  redis.call('ZADD', KEYS[1], now, ARGV[4])
  redis.call('PEXPIRE', KEYS[1], window)
  if daily_limit > 0 then
    redis.call('INCR', KEYS[2])
    redis.call('EXPIRE', KEYS[2], 172800)
  end
  return 0
end
local oldest = redis.call('ZRANGE', KEYS[1], count - allowed, count - allowed, 'WITHSCORES')
return math.max(1, tonumber(oldest[2]) + window - now)
"""


class RedisRateLimiter:
    """Limiter shared by every backend process through Redis, using Redis server time."""

    def __init__(self, config: LimiterConfig, url: str) -> None:
        from redis.asyncio import Redis

        self.name = config.name
        self._config = config
        self._redis: Redis = Redis.from_url(url, decode_responses=True)
        self._script = self._redis.register_script(_ACQUIRE_LUA)
        self._seq = 0

    def _keys(self) -> list[str]:
        today = datetime.now(UTC).date().isoformat()
        return [f"mp:rl:{self.name}:window", f"mp:rl:{self.name}:day:{today}"]

    async def acquire(self) -> None:
        cfg = self._config
        allowed = cfg.allowed_for(current_priority())
        deadline = time.monotonic() + cfg.max_wait_s
        while True:
            self._seq += 1
            member = f"{time.time_ns()}-{id(self)}-{self._seq}"
            args: list[str | int] = [int(cfg.window_s * 1000), allowed, cfg.daily_limit or 0, member]
            result = int(await self._script(keys=self._keys(), args=args))
            if result == 0:
                return
            if result == -1:
                raise RateLimitExceeded(cfg.name, f"daily budget of {cfg.daily_limit} calls used")
            wait = result / 1000
            if time.monotonic() + wait > deadline:
                raise RateLimitExceeded(cfg.name, f"limiter queue wait would exceed {cfg.max_wait_s:.0f}s")
            await asyncio.sleep(wait)

    async def usage(self) -> LimiterUsage:
        window_key, day_key = self._keys()
        now_ms = time.time() * 1000
        used = await self._redis.zcount(window_key, now_ms - self._config.window_s * 1000, "+inf")
        today = await self._redis.get(day_key)
        return LimiterUsage(
            name=self.name,
            used_in_window=int(used),
            limit_per_window=self._config.limit,
            window_s=self._config.window_s,
            used_today=int(today or 0),
            daily_limit=self._config.daily_limit,
        )

    async def close(self) -> None:
        await self._redis.aclose()


def build_limiter(config: LimiterConfig, redis_url: str) -> RateLimiter:
    return RedisRateLimiter(config, redis_url) if redis_url else MemoryRateLimiter(config)

import asyncio
import time
from dataclasses import replace
from typing import Any

import pytest

from app.core.errors import RateLimitExceeded
from app.core.ratelimit import LimiterConfig, MemoryRateLimiter, background_priority
from tests.conftest import FakeClock


def make_limiter(clock: FakeClock, **overrides: Any) -> MemoryRateLimiter:
    config = replace(LimiterConfig(name="finnhub", limit=50, window_s=60.0, max_wait_s=3600.0), **overrides)
    return MemoryRateLimiter(config, clock=clock, sleep=clock.sleep, today=lambda: "2026-10-19")


def max_in_any_window(timestamps: list[float], window: float) -> int:
    best = 0
    for i, start in enumerate(timestamps):
        best = max(best, sum(1 for t in timestamps[i:] if t < start + window))
    return best


async def test_burst_is_queued_and_never_exceeds_limit(clock: FakeClock) -> None:
    limiter = make_limiter(clock)
    stamps = []
    for _ in range(120):
        await limiter.acquire()
        stamps.append(clock.now)

    assert max_in_any_window(stamps, 60.0) == 50
    # 120 calls at 50/min need at least two full windows.
    assert stamps[-1] - stamps[0] >= 120.0
    assert stamps[49] == stamps[0]  # the first 50 go straight through
    assert stamps[50] == pytest.approx(stamps[0] + 60.0)


async def test_background_jobs_only_use_their_share(clock: FakeClock) -> None:
    limiter = make_limiter(clock, background_share=0.7)
    with background_priority():
        for _ in range(35):
            await limiter.acquire()
        start = clock.now
        await limiter.acquire()  # 36th background call must wait for the window to roll
        assert clock.now == pytest.approx(start + 60.0)


async def test_interactive_calls_keep_headroom_while_background_is_saturated(clock: FakeClock) -> None:
    limiter = make_limiter(clock, background_share=0.7)
    with background_priority():
        for _ in range(35):
            await limiter.acquire()
    start = clock.now
    for _ in range(15):
        await limiter.acquire()
    assert clock.now == start  # no waiting: 35 + 15 = 50


async def test_raises_when_queue_wait_exceeds_max_wait(clock: FakeClock) -> None:
    limiter = make_limiter(clock, limit=2, max_wait_s=5.0)
    await limiter.acquire()
    await limiter.acquire()
    with pytest.raises(RateLimitExceeded):
        await limiter.acquire()


async def test_daily_budget_is_enforced(clock: FakeClock) -> None:
    limiter = make_limiter(clock, limit=100, daily_limit=3)
    for _ in range(3):
        await limiter.acquire()
    with pytest.raises(RateLimitExceeded, match="daily budget"):
        await limiter.acquire()
    usage = await limiter.usage()
    assert usage.used_today == 3
    assert usage.daily_limit == 3


async def test_concurrent_callers_respect_the_limit_in_real_time() -> None:
    limiter = MemoryRateLimiter(LimiterConfig(name="rt", limit=5, window_s=0.3, max_wait_s=5.0))
    stamps: list[float] = []

    async def call() -> None:
        await limiter.acquire()
        stamps.append(time.monotonic())

    await asyncio.gather(*(call() for _ in range(15)))
    stamps.sort()
    assert len(stamps) == 15
    # Allow a little scheduler jitter at the window edge.
    assert max_in_any_window(stamps, 0.29) <= 5
    assert stamps[-1] - stamps[0] >= 0.55

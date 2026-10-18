from decimal import Decimal

import pytest
from pydantic import BaseModel

from app.core.cache import CacheBackend, MemoryCache, cached
from app.core.errors import NoDataError, ProviderError, RateLimitExceeded
from tests.conftest import FakeClock


class Price(BaseModel):
    symbol: str
    value: Decimal


class DummyProvider:
    name = "dummy"
    cache: CacheBackend

    def __init__(self, cache: MemoryCache) -> None:
        self.cache = cache
        self.calls = 0
        self.fail_with: Exception | None = None

    @cached(ttl=60)
    async def get_price(self, symbol: str) -> Price:
        self.calls += 1
        if self.fail_with is not None:
            raise self.fail_with
        return Price(symbol=symbol, value=Decimal("101.25"))


async def test_memory_cache_expires_entries(clock: FakeClock) -> None:
    cache = MemoryCache(clock=clock)
    await cache.set("k", "v", ttl_s=10)
    assert await cache.get("k") == "v"
    clock.now += 10
    assert await cache.get("k") is None


async def test_memory_cache_evicts_when_full(clock: FakeClock) -> None:
    cache = MemoryCache(clock=clock, max_entries=2)
    await cache.set("a", "1", ttl_s=10)
    await cache.set("b", "2", ttl_s=20)
    await cache.set("c", "3", ttl_s=30)
    assert await cache.get("a") is None  # soonest-expiring entry goes first
    assert await cache.get("c") == "3"


async def test_cached_returns_fresh_then_hits_cache(clock: FakeClock) -> None:
    provider = DummyProvider(MemoryCache(clock=clock))
    first = await provider.get_price("AAPL")
    second = await provider.get_price("AAPL")

    assert provider.calls == 1
    assert first.data == Price(symbol="AAPL", value=Decimal("101.25"))
    assert second.data == first.data
    assert second.as_of == first.as_of
    assert not first.stale and not second.stale
    assert first.source == "dummy"


async def test_cache_key_includes_arguments(clock: FakeClock) -> None:
    provider = DummyProvider(MemoryCache(clock=clock))
    await provider.get_price("AAPL")
    await provider.get_price("MSFT")
    assert provider.calls == 2


@pytest.mark.parametrize("error", [ProviderError("dummy", "boom"), RateLimitExceeded("dummy", "429")])
async def test_serves_stale_copy_after_provider_error(clock: FakeClock, error: Exception) -> None:
    provider = DummyProvider(MemoryCache(clock=clock))
    fresh = await provider.get_price("AAPL")
    clock.now += 61  # fresh entry expired, stale copy remains
    provider.fail_with = error

    result = await provider.get_price("AAPL")

    assert result.stale is True
    assert result.as_of == fresh.as_of
    assert result.data == fresh.data


async def test_raises_when_no_stale_copy_exists(clock: FakeClock) -> None:
    provider = DummyProvider(MemoryCache(clock=clock))
    provider.fail_with = ProviderError("dummy", "boom")
    with pytest.raises(ProviderError):
        await provider.get_price("AAPL")


async def test_no_data_is_not_masked_by_stale_copy(clock: FakeClock) -> None:
    provider = DummyProvider(MemoryCache(clock=clock))
    await provider.get_price("AAPL")
    clock.now += 61
    provider.fail_with = NoDataError("dummy", "delisted")
    with pytest.raises(NoDataError):
        await provider.get_price("AAPL")

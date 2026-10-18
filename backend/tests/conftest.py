from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
import respx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.models  # noqa: F401 - registers models on Base.metadata
from app.core.cache import MemoryCache
from app.core.ratelimit import LimiterConfig, MemoryRateLimiter
from app.db import Base, create_engine, create_session_factory

FAKE_FINNHUB_KEY = "test-finnhub-key-123"
FAKE_TWELVEDATA_KEY = "test-twelvedata-key-456"
FAKE_FRED_KEY = "test-fred-key-789"


class FakeClock:
    """Deterministic clock whose sleep() advances time instantly."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def cache() -> MemoryCache:
    return MemoryCache()


@pytest.fixture
def limiter() -> MemoryRateLimiter:
    return MemoryRateLimiter(LimiterConfig(name="test", limit=1000))


@pytest.fixture
def respx_mock() -> Iterator[respx.MockRouter]:
    # assert_all_called=False: some tests register routes for paths they expect *not* to be hit.
    with respx.mock(assert_all_called=False) as router:
        yield router


@pytest.fixture
async def http_client_factory() -> AsyncIterator[list[httpx.AsyncClient]]:
    clients: list[httpx.AsyncClient] = []
    yield clients
    for client in clients:
        await client.aclose()


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield create_session_factory(engine)
    await engine.dispose()

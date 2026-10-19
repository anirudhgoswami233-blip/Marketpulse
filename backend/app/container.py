"""Builds and owns the app's long-lived resources: cache, limiters, HTTP clients, providers, DB engine,
and the live-price hub and shared Finnhub WebSocket."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.cache import CacheBackend, build_cache
from app.core.config import Settings
from app.core.ratelimit import LimiterConfig, RateLimiter, build_limiter
from app.core.security import TokenSigner, build_signer
from app.db import create_engine, create_session_factory
from app.providers import finnhub, fred
from app.providers.base import MacroDataProvider, MarketDataProvider
from app.providers.fallback import twelvedata
from app.providers.registry import ProviderRegistry, UnconfiguredMacroProvider, UnconfiguredProvider
from app.ws.finnhub_stream import FinnhubStream
from app.ws.hub import PriceHub

logger = logging.getLogger(__name__)


@dataclass
class JobState:
    """Last run of a scheduled job, whether started by the in-process scheduler or the jobs endpoint."""

    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_started: datetime | None = None
    last_finished: datetime | None = None
    last_error: str | None = None


@dataclass
class Container:
    settings: Settings
    cache: CacheBackend
    limiters: dict[str, RateLimiter]
    providers: ProviderRegistry
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    hub: PriceHub
    signer: TokenSigner
    # None when FINNHUB_API_KEY is missing or streaming is disabled: pages then show REST quotes only.
    stream: FinnhubStream | None
    _clients: list[httpx.AsyncClient] = field(default_factory=list)
    # On-demand brief generation: users with a run in progress, and the tasks (kept so they aren't GC'd).
    briefs_in_progress: set[int] = field(default_factory=set)
    background_tasks: set[asyncio.Task[None]] = field(default_factory=set)
    jobs: dict[str, JobState] = field(default_factory=dict)

    def start_streaming(self) -> None:
        self.hub.start()
        if self.stream is not None:
            self.stream.start()

    def is_running(self, name: str) -> bool:
        return any(t.get_name() == name and not t.done() for t in self.background_tasks)

    def spawn(self, coro: Coroutine[Any, Any, None], name: str) -> None:
        task = asyncio.create_task(coro, name=name)
        self.background_tasks.add(task)
        task.add_done_callback(self.background_tasks.discard)

    async def close(self) -> None:
        for task in list(self.background_tasks):
            task.cancel()
        if self.stream is not None:
            await self.stream.stop()
        await self.hub.stop()
        for client in self._clients:
            await client.aclose()
        for limiter in self.limiters.values():
            close = getattr(limiter, "close", None)
            if close is not None:
                await close()
        await self.cache.close()
        await self.engine.dispose()


def check_shared_state(settings: Settings) -> None:
    """Rate limits and the Twelve Data daily budget are per API key at the vendor, so every backend process
    must share one limiter (Redis). The in-process fallback is only acceptable for a single dev server."""
    if settings.redis_url:
        return
    if settings.env != "dev":
        raise RuntimeError(
            "REDIS_URL must be set outside development: without it each process keeps its own rate limiter, "
            "and several processes on one API key can exceed the vendors' limits."
        )
    logger.warning(
        "REDIS_URL is not set: using an in-process cache and rate limiter. Run only one backend per set of "
        "API keys, or the processes' combined calls can exceed Finnhub's and Twelve Data's limits."
    )


def build_container(settings: Settings) -> Container:
    check_shared_state(settings)
    cache = build_cache(settings.redis_url)
    clients: list[httpx.AsyncClient] = []

    def limiter(name: str, per_minute: int, daily: int | None = None) -> RateLimiter:
        return build_limiter(
            LimiterConfig(
                name=name,
                limit=per_minute,
                background_share=settings.background_budget_share,
                daily_limit=daily,
                max_wait_s=settings.limiter_max_wait_s,
                background_max_wait_s=settings.limiter_background_max_wait_s,
            ),
            settings.redis_url,
        )

    limiters = {
        "finnhub": limiter("finnhub", settings.finnhub_calls_per_minute),
        "twelvedata": limiter(
            "twelvedata", settings.twelvedata_calls_per_minute, settings.twelvedata_calls_per_day
        ),
        "fred": limiter("fred", settings.fred_calls_per_minute),
    }

    primary: MarketDataProvider
    if settings.finnhub_api_key:
        client = finnhub.build_client(settings.finnhub_api_key.get_secret_value())
        clients.append(client)
        primary = finnhub.FinnhubProvider(client, limiters["finnhub"], cache)
    else:
        logger.warning("FINNHUB_API_KEY is not set; market data endpoints will be unavailable")
        primary = UnconfiguredProvider("finnhub", cache)

    fallback: MarketDataProvider
    if settings.twelvedata_api_key:
        client = twelvedata.build_client(settings.twelvedata_api_key.get_secret_value())
        clients.append(client)
        fallback = twelvedata.TwelveDataProvider(client, limiters["twelvedata"], cache)
    else:
        logger.warning(
            "TWELVEDATA_API_KEY is not set; charts, indicators and forex rates will be unavailable"
        )
        fallback = UnconfiguredProvider("twelvedata", cache)

    macro: MacroDataProvider
    if settings.fred_api_key:
        client = fred.build_client()
        clients.append(client)
        macro = fred.FredProvider(client, limiters["fred"], cache, settings.fred_api_key.get_secret_value())
    else:
        logger.warning("FRED_API_KEY is not set; the macro dashboard will be unavailable")
        macro = UnconfiguredMacroProvider("fred", cache)

    registry = ProviderRegistry(
        quotes=primary,
        reference=primary,
        news=primary,
        calendars=primary,
        market_status=primary,
        history=fallback,
        forex_rates=fallback,
        macro=macro,
        forex_quotes=fallback,
    )
    hub = PriceHub()
    stream = None
    if settings.enable_streaming and settings.finnhub_api_key:
        stream = FinnhubStream(
            settings.finnhub_api_key.get_secret_value(), hub, max_symbols=settings.finnhub_ws_max_symbols
        )

    engine = create_engine(settings.database_url)
    return Container(
        settings=settings,
        cache=cache,
        limiters=limiters,
        providers=registry,
        engine=engine,
        session_factory=create_session_factory(engine),
        hub=hub,
        signer=build_signer(settings),
        stream=stream,
        _clients=clients,
    )

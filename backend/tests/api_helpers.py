"""Shared setup for HTTP-level tests: an app on an in-memory DB, seeded symbols, and fake providers."""

from __future__ import annotations

import dataclasses
from typing import Any

import app.models  # noqa: F401 - registers models on Base.metadata
from app.container import Container
from app.core.config import Settings
from app.db import Base
from app.providers.base import SymbolRecord
from app.services import symbol_directory
from tests.fakes import FakeProvider

TEST_JWT_SECRET = "test-jwt-secret-that-is-long-enough-123456"


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": "sqlite+aiosqlite:///:memory:",
        "enable_background_jobs": False,
        "enable_streaming": False,
        "jwt_secret": TEST_JWT_SECRET,
        **overrides,
    }
    return Settings(_env_file=None, **values)


def _record(symbol: str, description: str, currency: str, mic: str) -> SymbolRecord:
    return SymbolRecord(
        symbol=symbol,
        display_symbol=symbol,
        description=description,
        type="Common Stock",
        currency=currency,
        mic=mic,
        figi=None,
    )


async def prepare(container: Container, provider: FakeProvider) -> None:
    async with container.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with container.session_factory() as session:
        await symbol_directory.upsert_exchanges(session, symbol_directory.load_exchange_rows())
        await symbol_directory.upsert_symbols(
            session,
            "US",
            [_record("AAPL", "APPLE INC", "USD", "XNAS"), _record("MSFT", "MICROSOFT CORP", "USD", "XNAS")],
        )
        await symbol_directory.upsert_symbols(session, "L", [_record("VOD", "VODAFONE", "GBP", "XLON")])
        await session.commit()
    container.providers = dataclasses.replace(
        container.providers,
        quotes=provider,
        reference=provider,
        news=provider,
        market_status=provider,
        history=provider,
    )

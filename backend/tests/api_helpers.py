"""Shared setup for HTTP-level tests: an app with seeded symbols and fake providers."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import app.models  # noqa: F401 - registers models on Base.metadata
from app.container import Container
from app.core.config import Settings
from app.db import Base
from app.providers.base import SymbolRecord
from app.services import symbol_directory
from tests.fakes import FakeProvider

TEST_JWT_SECRET = "test-jwt-secret-that-is-long-enough-123456"


def file_db(directory: Path) -> str:
    """A SQLite file URL for HTTP-level tests (pass pytest's `tmp_path`).

    Not ":memory:": an in-memory DB is served over one shared connection, so concurrent sessions (e.g. a
    background brief task and the requests polling it) would share one transaction, which never happens
    in a real deployment.
    """
    return f"sqlite+aiosqlite:///{(directory / 'test.db').as_posix()}"


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
        gold = SymbolRecord(
            symbol="OANDA:XAU_USD", display_symbol="XAU/USD", description="Oanda Gold", type="Forex",
            currency="USD", mic=None, figi=None,
        )  # fmt: skip
        silver = gold.model_copy(
            update={"symbol": "OANDA:XAG_USD", "display_symbol": "XAG/USD", "description": "Oanda Silver"}
        )
        await symbol_directory.upsert_symbols(session, "OANDA", [gold, silver])
        await symbol_directory.upsert_symbols(session, "FX", symbol_directory.extra_pair_records())
        await session.commit()
    container.providers = dataclasses.replace(
        container.providers,
        quotes=provider,
        reference=provider,
        news=provider,
        market_status=provider,
        calendars=provider,
        history=provider,
        forex_rates=provider,
        forex_quotes=provider,
    )

"""Loads the exchange list and symbol directory into the DB. Search reads the DB, never the provider."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import dialect_insert
from app.models import Exchange, Symbol
from app.providers.base import ForexSymbol, SymbolRecord
from app.services.reference_data import exchange_rows

logger = logging.getLogger(__name__)

FOREX_EXCHANGE = "OANDA"
# SQLite caps bound parameters per statement; 500 rows x 9 columns stays well under it.
CHUNK_SIZE = 500


EXCHANGE_COLUMNS = ("code", "name", "mic", "timezone", "currency", "country", "region")


def load_exchange_rows() -> list[dict[str, Any]]:
    # Trading sessions live only in the JSON file (see reference_data); the table holds the directory fields.
    return [{c: row.get(c) for c in EXCHANGE_COLUMNS} for row in exchange_rows()]


async def upsert_exchanges(session: AsyncSession, rows: Sequence[dict[str, Any]]) -> int:
    insert = dialect_insert(session)
    stmt = insert(Exchange).values(list(rows))
    stmt = stmt.on_conflict_do_update(
        index_elements=[Exchange.code],
        set_={c: stmt.excluded[c] for c in ("name", "mic", "timezone", "currency", "country", "region")},
    )
    await session.execute(stmt)
    return len(rows)


async def upsert_symbols(session: AsyncSession, exchange_code: str, records: Sequence[SymbolRecord]) -> int:
    """Insert or update every record; this exchange's symbols missing from `records` become inactive."""
    insert = dialect_insert(session)
    now = datetime.now(UTC)
    rows = [
        {
            "symbol": r.symbol,
            "exchange_code": exchange_code,
            "display_symbol": r.display_symbol,
            "description": r.description[:256],
            "type": r.type,
            "currency": r.currency,
            "mic": r.mic,
            "figi": r.figi,
            "is_active": True,
            "updated_at": now,
        }
        for r in records
    ]
    # Deactivate everything first; the upsert reactivates what the provider still lists. Same transaction, so
    # readers never see the gap. (Comparing updated_at timestamps was flaky on coarse clocks.)
    await session.execute(update(Symbol).where(Symbol.exchange_code == exchange_code).values(is_active=False))
    for start in range(0, len(rows), CHUNK_SIZE):
        stmt = insert(Symbol).values(rows[start : start + CHUNK_SIZE])
        stmt = stmt.on_conflict_do_update(
            index_elements=[Symbol.symbol, Symbol.exchange_code],
            set_={
                c: stmt.excluded[c]
                for c in (
                    "display_symbol",
                    "description",
                    "type",
                    "currency",
                    "mic",
                    "figi",
                    "is_active",
                    "updated_at",
                )
            },
        )
        await session.execute(stmt)
    return len(rows)


def forex_to_records(symbols: Sequence[ForexSymbol]) -> list[SymbolRecord]:
    return [
        SymbolRecord(
            symbol=s.symbol,
            display_symbol=s.display_symbol,
            description=s.description,
            type="Forex",
            currency=s.display_symbol.split("/")[-1] if "/" in s.display_symbol else None,
            mic=None,
            figi=None,
        )
        for s in symbols
    ]

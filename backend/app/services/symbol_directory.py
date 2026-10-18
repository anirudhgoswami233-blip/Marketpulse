"""Loads the exchange list and symbol directory into the DB. Search reads the DB, never the provider."""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Exchange, Symbol
from app.providers.base import ForexSymbol, SymbolRecord

logger = logging.getLogger(__name__)

EXCHANGES_FILE = Path(__file__).resolve().parents[1] / "data" / "exchanges.json"
FOREX_EXCHANGE = "OANDA"
# SQLite caps bound parameters per statement; 500 rows x 9 columns stays well under it.
CHUNK_SIZE = 500


def load_exchange_rows(path: Path = EXCHANGES_FILE) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
    return rows


def _insert(session: AsyncSession) -> Any:
    return pg_insert if session.get_bind().dialect.name == "postgresql" else sqlite_insert


async def upsert_exchanges(session: AsyncSession, rows: Sequence[dict[str, Any]]) -> int:
    insert = _insert(session)
    stmt = insert(Exchange).values(list(rows))
    stmt = stmt.on_conflict_do_update(
        index_elements=[Exchange.code],
        set_={c: stmt.excluded[c] for c in ("name", "mic", "timezone", "currency", "country", "region")},
    )
    await session.execute(stmt)
    return len(rows)


async def upsert_symbols(session: AsyncSession, exchange_code: str, records: Sequence[SymbolRecord]) -> int:
    """Insert or update every record, then mark this exchange's symbols that disappeared as inactive."""
    insert = _insert(session)
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
    await session.execute(
        update(Symbol)
        .where(Symbol.exchange_code == exchange_code, Symbol.updated_at < now)
        .values(is_active=False)
    )
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

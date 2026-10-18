from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Exchange, Symbol
from app.providers.base import ForexSymbol, SymbolRecord
from app.services import symbol_directory


def record(symbol: str, description: str = "") -> SymbolRecord:
    return SymbolRecord(
        symbol=symbol,
        display_symbol=symbol,
        description=description or f"{symbol} INC",
        type="Common Stock",
        currency="USD",
        mic="XNAS",
        figi=None,
    )


async def test_exchange_file_loads_and_upserts(session_factory: async_sessionmaker[AsyncSession]) -> None:
    rows = symbol_directory.load_exchange_rows()
    codes = {row["code"] for row in rows}
    assert {"US", "NS", "L", "T", "OANDA"} <= codes

    async with session_factory() as session:
        await symbol_directory.upsert_exchanges(session, rows)
        await symbol_directory.upsert_exchanges(session, rows)  # idempotent
        await session.commit()
        stored = (await session.execute(select(Exchange))).scalars().all()
    assert len(stored) == len(rows)
    assert next(e for e in stored if e.code == "NS").timezone == "Asia/Kolkata"


async def test_symbols_upsert_updates_and_deactivates_missing(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await symbol_directory.upsert_exchanges(session, symbol_directory.load_exchange_rows())
        await symbol_directory.upsert_symbols(session, "US", [record("AAPL"), record("OLDCO")])
        await session.commit()

        await symbol_directory.upsert_symbols(session, "US", [record("AAPL", "APPLE INC"), record("MSFT")])
        await session.commit()

        rows = {s.symbol: s for s in (await session.execute(select(Symbol))).scalars().all()}

    assert set(rows) == {"AAPL", "MSFT", "OLDCO"}
    assert rows["AAPL"].description == "APPLE INC"
    assert rows["AAPL"].is_active and rows["MSFT"].is_active
    assert rows["OLDCO"].is_active is False


async def test_forex_records_carry_quote_currency() -> None:
    records = symbol_directory.forex_to_records(
        [ForexSymbol(symbol="OANDA:USD_INR", display_symbol="USD/INR", description="Oanda USD/INR")]
    )
    assert records[0].type == "Forex"
    assert records[0].currency == "INR"

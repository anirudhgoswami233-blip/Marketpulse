"""Symbol search and lookup against the seeded symbol directory. Never calls a provider."""

from __future__ import annotations

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import SymbolNotFound
from app.models import Symbol

# Exchanges whose quotes and history our current providers can serve (see docs/finnhub-endpoints.md).
PRICED_EXCHANGES = frozenset({"US"})
STREAMABLE_EXCHANGES = frozenset({"US"})
# Operating companies first, then funds, then everything else (warrants, units, preferreds...).
TYPE_PRIORITY = {"Common Stock": 0, "ADR": 0, "ETP": 1}


def price_available(symbol: Symbol) -> bool:
    return symbol.exchange_code in PRICED_EXCHANGES


def streamable(symbol: Symbol) -> bool:
    return symbol.exchange_code in STREAMABLE_EXCHANGES


async def search_symbols(session: AsyncSession, query: str, limit: int = 20) -> list[Symbol]:
    q = query.strip()
    if not q:
        return []
    upper, lower = q.upper(), q.lower()
    description = func.lower(Symbol.description)
    rank = case(
        (Symbol.symbol == upper, 0),
        (Symbol.display_symbol == upper, 0),
        (Symbol.symbol.startswith(upper, autoescape=True), 1),
        (description.startswith(lower, autoescape=True), 2),
        else_=3,
    )
    # Ticker matches: shortest ticker first. Name matches: shortest name first, since the canonical company
    # ("APPLE INC") is usually shorter than look-alikes ("APPLE ISPORT GROUP INC").
    closeness = case(
        (Symbol.symbol.startswith(upper, autoescape=True), func.length(Symbol.symbol)),
        else_=func.length(Symbol.description),
    )
    type_rank = case(*((Symbol.type == t, p) for t, p in TYPE_PRIORITY.items()), else_=2)
    stmt = (
        select(Symbol)
        .where(
            Symbol.is_active.is_(True),
            or_(
                Symbol.symbol.startswith(upper, autoescape=True),
                Symbol.display_symbol.startswith(upper, autoescape=True),
                description.contains(lower, autoescape=True),
            ),
        )
        .order_by(rank, type_rank, closeness, Symbol.symbol)
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


async def resolve_symbol(session: AsyncSession, symbol: str, exchange: str | None = None) -> Symbol:
    """Find a directory entry by exact symbol, preferring the US listing for tickers listed elsewhere too."""
    stmt = select(Symbol).where(Symbol.symbol == symbol.upper())
    if exchange:
        stmt = stmt.where(Symbol.exchange_code == exchange.upper())
    stmt = stmt.order_by(case((Symbol.exchange_code == "US", 0), else_=1), Symbol.is_active.desc())
    found = (await session.execute(stmt.limit(1))).scalar_one_or_none()
    if found is None:
        raise SymbolNotFound(symbol)
    return found

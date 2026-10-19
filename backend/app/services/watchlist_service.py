"""Watchlists: per-user named lists of symbols. Every query is scoped to the owner."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.models import Symbol, Watchlist, WatchlistItem
from app.services.search_service import resolve_symbol

MAX_NAME_LENGTH = 60


@dataclass(frozen=True)
class WatchlistView:
    watchlist: Watchlist
    symbols: list[Symbol]


def _clean_name(name: str) -> str:
    cleaned = " ".join(name.split())
    if not cleaned or len(cleaned) > MAX_NAME_LENGTH:
        raise ValidationFailed(
            f"Watchlist names must be 1-{MAX_NAME_LENGTH} characters.", code="invalid_name"
        )
    return cleaned


async def _owned(session: AsyncSession, user_id: int, watchlist_id: int) -> Watchlist:
    watchlist = (
        await session.execute(
            select(Watchlist).where(Watchlist.id == watchlist_id, Watchlist.user_id == user_id)
        )
    ).scalar_one_or_none()
    if watchlist is None:
        # Same answer for "doesn't exist" and "belongs to someone else".
        raise NotFound("Watchlist not found.")
    return watchlist


async def list_watchlists(session: AsyncSession, user_id: int) -> list[WatchlistView]:
    watchlists = (
        (
            await session.execute(
                select(Watchlist)
                .where(Watchlist.user_id == user_id)
                .order_by(Watchlist.sort_order, Watchlist.id)
            )
        )
        .scalars()
        .all()
    )
    if not watchlists:
        return []
    rows = await session.execute(
        select(WatchlistItem.watchlist_id, Symbol)
        .join(Symbol, Symbol.id == WatchlistItem.symbol_id)
        .where(WatchlistItem.watchlist_id.in_([w.id for w in watchlists]))
        .order_by(WatchlistItem.sort_order, WatchlistItem.id)
    )
    by_list: dict[int, list[Symbol]] = {w.id: [] for w in watchlists}
    for watchlist_id, symbol in rows.all():
        by_list[watchlist_id].append(symbol)
    return [WatchlistView(w, by_list[w.id]) for w in watchlists]


async def get_watchlist(session: AsyncSession, user_id: int, watchlist_id: int) -> WatchlistView:
    await _owned(session, user_id, watchlist_id)
    return next(v for v in await list_watchlists(session, user_id) if v.watchlist.id == watchlist_id)


async def create_watchlist(session: AsyncSession, settings: Settings, user_id: int, name: str) -> Watchlist:
    cleaned = _clean_name(name)
    existing = (
        (await session.execute(select(Watchlist.name).where(Watchlist.user_id == user_id))).scalars().all()
    )
    if len(existing) >= settings.max_watchlists_per_user:
        raise ValidationFailed(
            f"You can have up to {settings.max_watchlists_per_user} watchlists.", code="limit_reached"
        )
    if cleaned.lower() in {n.lower() for n in existing}:
        raise Conflict("You already have a watchlist with that name.", code="duplicate_name")
    watchlist = Watchlist(user_id=user_id, name=cleaned, sort_order=len(existing))
    session.add(watchlist)
    await session.commit()
    return watchlist


async def rename_watchlist(session: AsyncSession, user_id: int, watchlist_id: int, name: str) -> Watchlist:
    watchlist = await _owned(session, user_id, watchlist_id)
    cleaned = _clean_name(name)
    clash = (
        await session.execute(
            select(Watchlist.id).where(
                Watchlist.user_id == user_id,
                func.lower(Watchlist.name) == cleaned.lower(),
                Watchlist.id != watchlist_id,
            )
        )
    ).first()
    if clash:
        raise Conflict("You already have a watchlist with that name.", code="duplicate_name")
    watchlist.name = cleaned
    await session.commit()
    return watchlist


async def delete_watchlist(session: AsyncSession, user_id: int, watchlist_id: int) -> None:
    watchlist = await _owned(session, user_id, watchlist_id)
    await session.delete(watchlist)
    await session.commit()


async def add_symbol(
    session: AsyncSession, settings: Settings, user_id: int, watchlist_id: int, symbol_code: str
) -> Symbol:
    watchlist = await _owned(session, user_id, watchlist_id)
    symbol = await resolve_symbol(session, symbol_code)
    count = (
        await session.execute(select(func.count()).where(WatchlistItem.watchlist_id == watchlist.id))
    ).scalar_one()
    if count >= settings.max_watchlist_items:
        raise ValidationFailed(
            f"A watchlist can hold up to {settings.max_watchlist_items} symbols.", code="limit_reached"
        )
    exists = (
        await session.execute(
            select(WatchlistItem.id).where(
                WatchlistItem.watchlist_id == watchlist.id, WatchlistItem.symbol_id == symbol.id
            )
        )
    ).first()
    if exists:
        raise Conflict(f"{symbol.display_symbol} is already on this watchlist.", code="duplicate_symbol")
    session.add(WatchlistItem(watchlist_id=watchlist.id, symbol_id=symbol.id, sort_order=count))
    await session.commit()
    return symbol


async def remove_symbol(session: AsyncSession, user_id: int, watchlist_id: int, symbol_code: str) -> None:
    watchlist = await _owned(session, user_id, watchlist_id)
    item = (
        await session.execute(
            select(WatchlistItem)
            .join(Symbol, Symbol.id == WatchlistItem.symbol_id)
            .where(WatchlistItem.watchlist_id == watchlist.id, Symbol.symbol == symbol_code.upper())
        )
    ).scalar_one_or_none()
    if item is None:
        raise NotFound(f"{symbol_code.upper()} isn't on this watchlist.")
    await session.delete(item)
    await session.commit()

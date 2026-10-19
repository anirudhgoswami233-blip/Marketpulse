"""Daily Brief assembly: who is due, which symbols, overnight summary, and the stored brief.

Signals are computed once per symbol (shared across users) by the caller, at background priority, before
briefs are built. Building a brief itself makes no external calls.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import CacheBackend
from app.jobs.templates.brief import BriefItem, RegionMove, render
from app.models import Brief, BriefSignal, SignalRecord, Symbol, User, Watchlist, WatchlistItem
from app.services.markets_service import load_snapshot
from app.services.reference_data import overview_config
from app.services.search_service import price_available

logger = logging.getLogger(__name__)

MAX_WATCHLIST_SYMBOLS = 25
TRENDING_PER_SIDE = 3


def local_now(user: User, now: datetime) -> datetime:
    try:
        return now.astimezone(ZoneInfo(user.timezone))
    except (KeyError, ValueError):
        return now.astimezone(UTC)


def is_due(user: User, now: datetime, has_brief_today: bool) -> bool:
    """Weekday mornings in the user's own timezone, once their chosen brief time has passed."""
    local = local_now(user, now)
    return local.weekday() < 5 and local.time() >= user.brief_time and not has_brief_today


async def due_users(session: AsyncSession, now: datetime) -> list[User]:
    users = (await session.execute(select(User))).scalars().all()
    due = []
    for user in users:
        today = local_now(user, now).date()
        exists = (
            await session.execute(select(Brief.id).where(Brief.user_id == user.id, Brief.brief_date == today))
        ).first()
        if is_due(user, now, exists is not None):
            due.append(user)
    return due


@dataclass(frozen=True)
class BriefSymbol:
    symbol: Symbol
    source: str  # "watchlist" | "trending"


async def brief_symbols(session: AsyncSession, cache: CacheBackend, user: User) -> list[BriefSymbol]:
    rows = (
        (
            await session.execute(
                select(Symbol)
                .join(WatchlistItem, WatchlistItem.symbol_id == Symbol.id)
                .join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id)
                .where(Watchlist.user_id == user.id)
                .order_by(Watchlist.sort_order, WatchlistItem.sort_order, WatchlistItem.id)
            )
        )
        .scalars()
        .all()
    )
    chosen: dict[int, BriefSymbol] = {}
    for symbol in rows:
        if price_available(symbol) and symbol.id not in chosen and len(chosen) < MAX_WATCHLIST_SYMBOLS:
            chosen[symbol.id] = BriefSymbol(symbol, "watchlist")

    # Trending: today's biggest movers from the overview snapshot (no extra API calls).
    snapshot = await load_snapshot(cache)
    movers = sorted(
        (
            q
            for s, q in snapshot.quotes.items()
            if s in overview_config().movers_universe and q.change_pct is not None
        ),
        key=lambda q: q.change_pct or 0,
    )
    trending_codes = [q.symbol for q in movers[-TRENDING_PER_SIDE:][::-1] + movers[:TRENDING_PER_SIDE]]
    if trending_codes:
        trending = (
            (
                await session.execute(
                    select(Symbol).where(Symbol.symbol.in_(trending_codes), Symbol.exchange_code == "US")
                )
            )
            .scalars()
            .all()
        )
        for symbol in sorted(trending, key=lambda s: trending_codes.index(s.symbol)):
            if symbol.id not in chosen:
                chosen[symbol.id] = BriefSymbol(symbol, "trending")
    return list(chosen.values())


async def overnight_moves(cache: CacheBackend) -> tuple[list[RegionMove], dict[str, Any]]:
    snapshot = await load_snapshot(cache)
    moves: list[RegionMove] = []
    regions_json = []
    for region in overview_config().regions:
        changes = []
        details = []
        for index in region.indices:
            quote = snapshot.quotes.get(index.symbol)
            if quote is not None and quote.change_pct is not None:
                changes.append(float(quote.change_pct))
                details.append(f"{index.symbol} ({index.name}) {float(quote.change_pct):+.2f}%")
        avg = sum(changes) / len(changes) if changes else None
        moves.append(RegionMove(region.region, avg, ", ".join(details) or "no data"))
        regions_json.append({"region": region.region, "avg_change_pct": avg, "detail": details})
    as_of = snapshot.updated_at.isoformat() if snapshot.updated_at else None
    return moves, {"regions": regions_json, "as_of": as_of, "proxies": "US-listed ETFs tracking each region"}


@dataclass(frozen=True)
class BriefContext:
    user: User
    brief_date: date
    moves: Sequence[RegionMove]
    items: Sequence[BriefItem]
    unavailable: Sequence[str]


class BriefWriter(Protocol):
    name: str

    async def write(self, context: BriefContext) -> str: ...


class TemplateWriter:
    name = "template"

    async def write(self, context: BriefContext) -> str:
        return render(
            context.user.display_name, context.brief_date, context.moves, context.items, context.unavailable
        )


async def build_brief(
    session: AsyncSession,
    cache: CacheBackend,
    writer: BriefWriter,
    user: User,
    symbols: Sequence[BriefSymbol],
    signals: dict[int, SignalRecord],
    now: datetime,
) -> Brief:
    """Store (or replace) the user's brief for their local date from already-computed signals."""
    brief_date = local_now(user, now).date()
    moves, overnight = await overnight_moves(cache)
    items, unavailable, links = [], [], []
    for entry in symbols:
        record = signals.get(entry.symbol.id)
        if record is None:
            unavailable.append(entry.symbol.display_symbol)
            continue
        items.append(
            BriefItem(
                symbol=entry.symbol.display_symbol,
                name=entry.symbol.description,
                source=entry.source,
                label=record.label,
                score=record.score,
                reasons=[r["reason"] for r in record.reasons],
            )
        )
        links.append((record.id, entry.source))
    overnight["unavailable"] = unavailable

    context = BriefContext(user, brief_date, moves, items, unavailable)
    summary = await writer.write(context)
    await session.execute(delete(Brief).where(Brief.user_id == user.id, Brief.brief_date == brief_date))
    brief = Brief(
        user_id=user.id,
        brief_date=brief_date,
        generated_at=now,
        generator=writer.name,
        summary_md=summary,
        overnight=overnight,
    )
    session.add(brief)
    await session.flush()
    for signal_id, source in dict(links).items():
        session.add(BriefSignal(brief_id=brief.id, signal_id=signal_id, source=source))
    await session.commit()
    logger.info("Built brief %s for user %s (%d signals)", brief_date, user.id, len(links))
    return brief

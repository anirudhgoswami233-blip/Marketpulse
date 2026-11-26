"""Daily Brief assembly: who is due, which symbols, overnight summary, and the stored brief.

Signals are computed once per symbol (shared across users) by the caller, at background priority, before
briefs are built. Building a brief makes no market-data calls; the optional LLM prose rewrite (when
`LLM_API_KEY` is set) is the only external call, and it falls back to the template on any failure.
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
from app.core.llm import LLMClient, LLMError
from app.jobs.templates.brief import BriefItem, NewsLine, RegionMove, render
from app.models import Brief, BriefSignal, SignalRecord, Symbol, User, Watchlist, WatchlistItem
from app.services.markets_service import load_snapshot
from app.services.news_service import NewsHighlight
from app.services.reference_data import overview_config
from app.services.search_service import price_available
from app.signals.engine import DISCLAIMER

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
    news: Sequence[NewsLine] = ()


@dataclass(frozen=True)
class WrittenBrief:
    text: str
    generator: str  # "template" | "llm"


class BriefWriter(Protocol):
    async def write(self, context: BriefContext) -> WrittenBrief: ...


def _template_text(context: BriefContext) -> str:
    return render(
        context.user.display_name,
        context.brief_date,
        context.moves,
        context.items,
        context.unavailable,
        context.news,
    )


class TemplateWriter:
    async def write(self, context: BriefContext) -> WrittenBrief:
        return WrittenBrief(_template_text(context), "template")


BRIEF_SYSTEM = (
    "You rewrite a pre-computed daily stock-market brief into clear, concise prose for a retail investor. "
    "Use ONLY the facts provided. Never invent numbers, prices, signals, or news. Report the technical "
    "signals as descriptive readings with their reasons; never tell the reader to buy, sell, or hold, and "
    "never give a recommendation or price target. Keep it brief and skimmable with short Markdown sections. "
    "End with this exact line and nothing after it: "
    f"_{DISCLAIMER}_"
)


def _llm_prompt(context: BriefContext) -> str:
    lines = [
        f"Date: {context.brief_date:%A, %d %B %Y}",
        f"Reader: {context.user.display_name}",
        "",
        "Overnight (regional ETF proxies):",
    ]
    lines += [f"- {m.region}: {m.detail}" for m in context.moves]
    if context.news:
        lines += ["", "Material news (descriptive labels only):"]
        lines += [f"- {n.symbol} [{n.category_label}, {n.materiality}]: {n.headline}" for n in context.news]
    lines += ["", "Signals (label, score, reasons — do not alter the numbers):"]
    for item in context.items:
        reasons = "; ".join(item.reasons) if item.reasons else "no indicator readings"
        lines.append(
            f"- {item.symbol} ({item.name}) [{item.source}]: {item.label} (score {item.score:+d}). {reasons}"
        )
    if context.unavailable:
        lines += ["", f"No signal today for: {', '.join(context.unavailable)}"]
    return "\n".join(lines)


def _ensure_disclaimer(text: str) -> str:
    return text if DISCLAIMER in text else f"{text.rstrip()}\n\n---\n\n_{DISCLAIMER}_"


class LLMWriter:
    """Rewrites the computed brief into prose with the LLM; falls back to the template on any failure."""

    def __init__(self, client: LLMClient) -> None:
        self._client = client

    async def write(self, context: BriefContext) -> WrittenBrief:
        try:
            text = await self._client.complete(BRIEF_SYSTEM, _llm_prompt(context), max_tokens=1400)
        except LLMError as exc:
            logger.warning("Brief LLM rewrite failed; using template: %s", exc)
            return WrittenBrief(_template_text(context), "template")
        return WrittenBrief(_ensure_disclaimer(text), "llm")


async def build_brief(
    session: AsyncSession,
    cache: CacheBackend,
    writer: BriefWriter,
    user: User,
    symbols: Sequence[BriefSymbol],
    signals: dict[int, SignalRecord],
    now: datetime,
    news: dict[int, NewsHighlight] | None = None,
) -> Brief:
    """Store (or replace) the user's brief for their local date from already-computed signals and news."""
    news = news or {}
    brief_date = local_now(user, now).date()
    moves, overnight = await overnight_moves(cache)
    items, unavailable, links = [], [], []
    highlights: list[NewsHighlight] = []
    for entry in symbols:
        if entry.symbol.id in news and all(h.symbol != news[entry.symbol.id].symbol for h in highlights):
            highlights.append(news[entry.symbol.id])
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
    overnight["headlines"] = [h.to_dict() for h in highlights]

    news_lines = [
        NewsLine(
            symbol=h.display_symbol,
            category_label=h.category_label,
            materiality=h.materiality,
            headline=h.headline,
        )
        for h in highlights
    ]
    context = BriefContext(user, brief_date, moves, items, unavailable, news_lines)
    written = await writer.write(context)
    await session.execute(delete(Brief).where(Brief.user_id == user.id, Brief.brief_date == brief_date))
    brief = Brief(
        user_id=user.id,
        brief_date=brief_date,
        generated_at=now,
        generator=written.generator,
        summary_md=written.text,
        overnight=overnight,
    )
    session.add(brief)
    await session.flush()
    for signal_id, source in dict(links).items():
        session.add(BriefSignal(brief_id=brief.id, signal_id=signal_id, source=source))
    await session.commit()
    logger.info("Built brief %s for user %s (%d signals)", brief_date, user.id, len(links))
    return brief

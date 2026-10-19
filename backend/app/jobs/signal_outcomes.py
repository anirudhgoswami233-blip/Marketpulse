"""Records how stored signals played out after 1, 5 and 20 trading sessions, for the Signal History page.

Outcomes come from stored daily bars. A symbol whose bars are behind gets one history top-up per run
(at background priority), so this job costs at most one history call per symbol per day.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.container import Container
from app.core.errors import ProviderError
from app.core.ratelimit import background_priority
from app.db import dialect_insert
from app.models import PriceBar, SignalOutcome, SignalRecord, Symbol
from app.services import history_service
from app.services.market_hours import last_completed_session_date
from app.services.reference_data import exchange_schedules
from app.signals.performance import HORIZONS, outcome_for

logger = logging.getLogger(__name__)

MAX_SIGNALS_PER_RUN = 500


async def pending_signals(session: AsyncSession) -> list[SignalRecord]:
    done = (
        select(SignalOutcome.signal_id)
        .group_by(SignalOutcome.signal_id)
        .having(func.count() >= len(HORIZONS))
    )
    stmt = (
        select(SignalRecord)
        .where(SignalRecord.id.not_in(done), SignalRecord.price_at_signal.is_not(None))
        .order_by(SignalRecord.signal_date)
        .limit(MAX_SIGNALS_PER_RUN)
    )
    return list((await session.execute(stmt)).scalars().all())


async def evaluate_outcomes(session: AsyncSession, container: Container | None, now: datetime) -> int:
    """Store every outcome that's now measurable. `container=None` skips history top-ups (tests)."""
    pending = await pending_signals(session)
    by_symbol: dict[int, list[SignalRecord]] = defaultdict(list)
    for record in pending:
        by_symbol[record.symbol_id].append(record)

    stored = 0
    for symbol_id, records in by_symbol.items():
        symbol = await session.get(Symbol, symbol_id)
        if symbol is None:
            continue
        if container is not None:
            await _top_up(container, symbol, now)
        earliest = min(r.signal_date for r in records)
        bars = (
            await session.execute(
                select(PriceBar.date, PriceBar.close)
                .where(PriceBar.symbol_id == symbol_id, PriceBar.date > earliest)
                .order_by(PriceBar.date)
            )
        ).all()
        existing = {
            (o.signal_id, o.horizon_days)
            for o in (
                await session.execute(
                    select(SignalOutcome).where(SignalOutcome.signal_id.in_([r.id for r in records]))
                )
            ).scalars()
        }
        for record in records:
            after = [(d, c) for d, c in bars if d > record.signal_date]
            for horizon in HORIZONS:
                if (record.id, horizon) in existing or record.price_at_signal is None:
                    continue
                outcome = outcome_for(record.price_at_signal, after, horizon)
                if outcome is None:
                    continue
                insert = dialect_insert(session)
                await session.execute(
                    insert(SignalOutcome)
                    .values(
                        signal_id=record.id,
                        horizon_days=horizon,
                        outcome_date=outcome.outcome_date,
                        price_after=outcome.price_after,
                        return_pct=outcome.return_pct,
                        evaluated_at=now,
                    )
                    .on_conflict_do_nothing(index_elements=["signal_id", "horizon_days"])
                )
                stored += 1
        await session.commit()
    return stored


async def _top_up(container: Container, symbol: Symbol, now: datetime) -> None:
    schedule = exchange_schedules().get(symbol.exchange_code) or exchange_schedules()["US"]
    target = last_completed_session_date(schedule, now)
    # Separate session: a failed top-up's rollback must not expire the signals being evaluated.
    async with container.session_factory() as session:
        with background_priority():
            try:
                # get_daily_bars only calls the provider when stored bars are behind `target`.
                await history_service.get_daily_bars(
                    session, container.providers.history, container.cache, symbol, target, now
                )
            except ProviderError as exc:
                logger.info("Outcome top-up skipped for %s: %s", symbol.symbol, exc)


async def run(container: Container) -> None:
    now = datetime.now(UTC)
    async with container.session_factory() as session:
        stored = await evaluate_outcomes(session, container, now)
    if stored:
        logger.info("Recorded %d signal outcomes", stored)

import logging
from datetime import UTC, date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ContainerDep, CurrentUser, SessionDep, SymbolDep
from app.container import Container
from app.core.errors import NotFound
from app.jobs import daily_brief
from app.models import Brief, BriefSignal, SignalOutcome, SignalRecord, Symbol, User
from app.schemas.signals import (
    BriefItemOut,
    BriefOut,
    BriefStatus,
    BriefSummaryOut,
    LabelStatsOut,
    OutcomeOut,
    PerformanceOut,
    SignalOut,
    SignalReason,
    SkippedRule,
)
from app.services import brief_service, signal_service
from app.services.email_service import email_configured
from app.signals.engine import Label
from app.signals.performance import MIN_SAMPLE, summarize

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["signals"])


def signal_out(
    record: SignalRecord, symbol: Symbol, outcomes: list[SignalOutcome] | None = None
) -> SignalOut:
    return SignalOut(
        id=record.id,
        symbol=symbol.symbol,
        display_symbol=symbol.display_symbol,
        description=symbol.description,
        signal_date=record.signal_date,
        engine_version=record.engine_version,
        score=record.score,
        label=record.label,
        reasons=[SignalReason(**r) for r in record.reasons],
        skipped=[SkippedRule(**s) for s in record.skipped],
        indicators=record.indicators,
        price_at_signal=record.price_at_signal,
        currency=record.currency,
        outcomes=[
            OutcomeOut(horizon_days=o.horizon_days, outcome_date=o.outcome_date, return_pct=o.return_pct)
            for o in sorted(outcomes or [], key=lambda o: o.horizon_days)
        ],
    )


async def _outcomes_for(session: AsyncSession, signal_ids: list[int]) -> dict[int, list[SignalOutcome]]:
    if not signal_ids:
        return {}
    rows = (
        await session.execute(select(SignalOutcome).where(SignalOutcome.signal_id.in_(signal_ids)))
    ).scalars()
    by_signal: dict[int, list[SignalOutcome]] = {}
    for outcome in rows:
        by_signal.setdefault(outcome.signal_id, []).append(outcome)
    return by_signal


@router.get("/stocks/{symbol}/signal", response_model=SignalOut)
async def stock_signal(symbol: SymbolDep, session: SessionDep, container: ContainerDep) -> SignalOut:
    record = await signal_service.get_or_compute(
        session, container.providers.history, container.providers.news, container.cache, symbol
    )
    outcomes = await _outcomes_for(session, [record.id])
    return signal_out(record, symbol, outcomes.get(record.id))


@router.get("/signals/history", response_model=list[SignalOut])
async def signal_history(
    session: SessionDep,
    symbol: Annotated[str | None, Query(max_length=32)] = None,
    label: Annotated[Literal["Bullish signals", "Neutral", "Bearish signals"] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[SignalOut]:
    stmt = select(SignalRecord, Symbol).join(Symbol, Symbol.id == SignalRecord.symbol_id)
    if symbol:
        stmt = stmt.where(Symbol.symbol == symbol.upper())
    if label:
        stmt = stmt.where(SignalRecord.label == label)
    rows = (
        await session.execute(
            stmt.order_by(SignalRecord.signal_date.desc(), SignalRecord.id.desc()).limit(limit)
        )
    ).all()
    outcomes = await _outcomes_for(session, [r.id for r, _ in rows])
    return [signal_out(r, s, outcomes.get(r.id)) for r, s in rows]


@router.get("/signals/performance", response_model=PerformanceOut)
async def signal_performance(session: SessionDep) -> PerformanceOut:
    rows = (
        await session.execute(
            select(SignalRecord.label, SignalOutcome.horizon_days, SignalOutcome.return_pct).join(
                SignalOutcome, SignalOutcome.signal_id == SignalRecord.id
            )
        )
    ).all()
    total = (await session.execute(select(func.count()).select_from(SignalRecord))).scalar_one()
    stats = summarize([(label, horizon, ret) for label, horizon, ret in rows])
    return PerformanceOut(
        stats=[LabelStatsOut.model_validate(s, from_attributes=True) for s in stats],
        total_signals=total,
        min_sample=MIN_SAMPLE,
    )


# --- Daily Brief --------------------------------------------------------------------------------------


async def _brief_out(session: AsyncSession, brief: Brief) -> BriefOut:
    rows = (
        await session.execute(
            select(BriefSignal.source, SignalRecord, Symbol)
            .join(SignalRecord, SignalRecord.id == BriefSignal.signal_id)
            .join(Symbol, Symbol.id == SignalRecord.symbol_id)
            .where(BriefSignal.brief_id == brief.id)
        )
    ).all()
    label_order = {Label.BULLISH.value: 0, Label.BEARISH.value: 1, Label.NEUTRAL.value: 2}
    items = sorted(
        (BriefItemOut(source=source, signal=signal_out(record, symbol)) for source, record, symbol in rows),
        key=lambda i: (i.source != "watchlist", label_order.get(i.signal.label, 3), -abs(i.signal.score)),
    )
    return BriefOut(
        id=brief.id,
        brief_date=brief.brief_date,
        generated_at=brief.generated_at,
        generator=brief.generator,
        summary_md=brief.summary_md,
        overnight=brief.overnight,
        items=items,
        emailed_at=brief.emailed_at,
    )


def _next_scheduled(user: User, now: datetime) -> datetime | None:
    local = brief_service.local_now(user, now)
    if local.weekday() >= 5:
        return None
    scheduled = local.replace(
        hour=user.brief_time.hour, minute=user.brief_time.minute, second=0, microsecond=0
    )
    return scheduled.astimezone(UTC)


@router.get("/brief", response_model=BriefStatus)
async def latest_brief(user: CurrentUser, session: SessionDep, container: ContainerDep) -> BriefStatus:
    brief = (
        await session.execute(
            select(Brief).where(Brief.user_id == user.id).order_by(Brief.brief_date.desc()).limit(1)
        )
    ).scalar_one_or_none()
    return BriefStatus(
        brief=await _brief_out(session, brief) if brief else None,
        generating=user.id in container.briefs_in_progress,
        next_scheduled_at=_next_scheduled(user, datetime.now(UTC)),
        email_available=email_configured(container.settings),
    )


@router.get("/briefs", response_model=list[BriefSummaryOut])
async def list_briefs(
    user: CurrentUser, session: SessionDep, limit: Annotated[int, Query(ge=1, le=60)] = 14
) -> list[BriefSummaryOut]:
    briefs = (
        (
            await session.execute(
                select(Brief).where(Brief.user_id == user.id).order_by(Brief.brief_date.desc()).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    out = []
    for brief in briefs:
        count = len(
            (
                await session.execute(select(BriefSignal.signal_id).where(BriefSignal.brief_id == brief.id))
            ).all()
        )
        out.append(
            BriefSummaryOut(brief_date=brief.brief_date, generated_at=brief.generated_at, signal_count=count)
        )
    return out


@router.get("/briefs/{brief_date}", response_model=BriefOut)
async def get_brief(brief_date: date, user: CurrentUser, session: SessionDep) -> BriefOut:
    brief = (
        await session.execute(select(Brief).where(Brief.user_id == user.id, Brief.brief_date == brief_date))
    ).scalar_one_or_none()
    if brief is None:
        raise NotFound("No brief for that date.")
    return await _brief_out(session, brief)


@router.post("/brief/generate", status_code=status.HTTP_202_ACCEPTED)
async def generate_brief(user: CurrentUser, container: ContainerDep) -> Response:
    """Build today's brief now, in the background (signals may need a few minutes to compute)."""
    if user.id not in container.briefs_in_progress:
        container.briefs_in_progress.add(user.id)
        container.spawn(_generate_now(container, user), name=f"brief-{user.id}")
    return Response(status_code=status.HTTP_202_ACCEPTED)


async def _generate_now(container: Container, user: User) -> None:
    try:
        await daily_brief.generate_for(container, [user])
    except Exception:
        logger.exception("On-demand brief failed for user %s", user.id)
    finally:
        container.briefs_in_progress.discard(user.id)

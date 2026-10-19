"""Forex & metals board, macro dashboard and earnings/IPO calendars."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.api.deps import ContainerDep, OptionalUserId, SessionDep
from app.core.errors import Unauthorized
from app.jobs import forex_snapshot
from app.providers.base import EarningsSession
from app.services import calendar_service, forex_service, macro_service

router = APIRouter(prefix="/api/v1", tags=["world"])


@router.get("/forex", response_model=forex_service.ForexBoard)
async def forex_board(container: ContainerDep) -> forex_service.ForexBoard:
    interval = timedelta(seconds=container.settings.forex_refresh_s)
    now = datetime.now(UTC)
    snapshot = await forex_service.load_snapshot(container.cache)
    if forex_service.needs_refresh(snapshot, now, interval):
        forex_snapshot.start_refresh(container)
    refreshing = container.is_running(forex_snapshot.TASK_NAME)
    return forex_service.build_board(snapshot, now, interval, refreshing)


@router.get("/macro", response_model=macro_service.MacroDashboard)
async def macro(container: ContainerDep) -> macro_service.MacroDashboard:
    return await macro_service.dashboard(container.providers.macro)


class EarningsRow(BaseModel):
    symbol: str
    name: str | None
    date: date
    session: EarningsSession
    quarter: int | None
    year: int | None
    eps_estimate: Decimal | None
    eps_actual: Decimal | None
    eps_surprise_pct: Decimal | None
    revenue_estimate: Decimal | None
    revenue_actual: Decimal | None
    in_watchlist: bool


class EarningsWeek(BaseModel):
    week_start: date
    week_end: date
    events: list[EarningsRow]
    total: int
    as_of: datetime
    stale: bool


class IpoRow(BaseModel):
    symbol: str | None
    name: str
    date: date
    exchange: str | None
    status: str | None
    price_range: str | None
    shares: int | None
    total_value: Decimal | None


class IpoWeek(BaseModel):
    week_start: date
    week_end: date
    events: list[IpoRow]
    as_of: datetime
    stale: bool


@router.get("/calendar/earnings", response_model=EarningsWeek)
async def earnings(
    container: ContainerDep,
    session: SessionDep,
    user_id: OptionalUserId,
    week: Annotated[date | None, Query(description="Any date in the week (Mon-Sun)")] = None,
    watchlist_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=2000)] = 500,
) -> EarningsWeek:
    if watchlist_only and user_id is None:
        raise Unauthorized("Sign in to filter by your watchlists.", code="not_authenticated")
    day = week or datetime.now(UTC).date()
    start, end = calendar_service.week_bounds(day)
    fetched = await calendar_service.earnings_week(container.providers.calendars, day)
    mine = await calendar_service.watchlist_symbols(session, user_id) if user_id else set()
    events = [e for e in fetched.data if not watchlist_only or e.symbol in mine]
    # Watchlist names first within each day, then alphabetically.
    events.sort(key=lambda e: (e.date, e.symbol not in mine, e.symbol))
    names = await calendar_service.company_names(session, [e.symbol for e in events[:limit]])
    rows = [
        EarningsRow(
            symbol=e.symbol,
            name=names.get(e.symbol),
            date=e.date,
            session=e.session,
            quarter=e.quarter,
            year=e.year,
            eps_estimate=e.eps_estimate,
            eps_actual=e.eps_actual,
            eps_surprise_pct=calendar_service.surprise_pct(e.eps_actual, e.eps_estimate),
            revenue_estimate=e.revenue_estimate,
            revenue_actual=e.revenue_actual,
            in_watchlist=e.symbol in mine,
        )
        for e in events[:limit]
    ]
    return EarningsWeek(
        week_start=start,
        week_end=end,
        events=rows,
        total=len(events),
        as_of=fetched.as_of,
        stale=fetched.stale,
    )


@router.get("/calendar/ipos", response_model=IpoWeek)
async def ipos(
    container: ContainerDep, week: Annotated[date | None, Query(description="Any date in the week")] = None
) -> IpoWeek:
    day = week or datetime.now(UTC).date()
    start, end = calendar_service.week_bounds(day)
    fetched = await calendar_service.ipos_week(container.providers.calendars, day)
    events = sorted(fetched.data, key=lambda e: (e.date, e.name))
    return IpoWeek(
        week_start=start,
        week_end=end,
        events=[IpoRow.model_validate(e, from_attributes=True) for e in events],
        as_of=fetched.as_of,
        stale=fetched.stale,
    )

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter

from app.api.deps import ContainerDep, SessionDep
from app.container import Container
from app.jobs.runner import is_job_running, run_exclusive
from app.schemas.markets import MarketOverview, MarketStatusOut, ScreenerOut
from app.services import markets_service, screener_service

SCREENER_JOB = "screener_snapshot"

router = APIRouter(prefix="/api/v1/markets", tags=["markets"])


@router.get("/overview", response_model=MarketOverview)
async def overview(container: ContainerDep) -> MarketOverview:
    # A snapshot older than ~3 refresh cycles during US hours is flagged stale.
    stale_after = timedelta(seconds=container.settings.overview_refresh_open_s * 3)
    return await markets_service.get_overview(
        container.providers.market_status, container.cache, datetime.now(UTC), stale_after
    )


@router.get("/screener", response_model=ScreenerOut)
async def screener(container: ContainerDep, session: SessionDep) -> ScreenerOut:
    now = datetime.now(UTC)
    # The first visit (or the first after a day) starts the background refresh; the page shows what's ready.
    if (
        container.settings.enable_background_jobs
        and not is_job_running(container, SCREENER_JOB)
        and screener_service.needs_refresh(await screener_service.load_fundamentals(container.cache), now)
    ):
        container.spawn(_run_screener_job(container), name=f"job:{SCREENER_JOB}")
    return await screener_service.get_screener(
        session, container.cache, now, refreshing=is_job_running(container, SCREENER_JOB)
    )


async def _run_screener_job(container: Container) -> None:
    await run_exclusive(container, SCREENER_JOB)


@router.get("/status", response_model=list[MarketStatusOut])
async def status(container: ContainerDep) -> list[MarketStatusOut]:
    return await markets_service.market_statuses(container.providers.market_status, datetime.now(UTC))

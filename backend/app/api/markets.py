from datetime import UTC, datetime, timedelta

from fastapi import APIRouter

from app.api.deps import ContainerDep
from app.schemas.markets import MarketOverview, MarketStatusOut
from app.services import markets_service

router = APIRouter(prefix="/api/v1/markets", tags=["markets"])


@router.get("/overview", response_model=MarketOverview)
async def overview(container: ContainerDep) -> MarketOverview:
    # A snapshot older than ~3 refresh cycles during US hours is flagged stale.
    stale_after = timedelta(seconds=container.settings.overview_refresh_open_s * 3)
    return await markets_service.get_overview(
        container.providers.market_status, container.cache, datetime.now(UTC), stale_after
    )


@router.get("/status", response_model=list[MarketStatusOut])
async def status(container: ContainerDep) -> list[MarketStatusOut]:
    return await markets_service.market_statuses(container.providers.market_status, datetime.now(UTC))

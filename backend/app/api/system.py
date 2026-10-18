from fastapi import APIRouter, Request

from app.container import Container
from app.schemas.system import LimiterStatus, ProviderStatus, SystemStatus

router = APIRouter(tags=["system"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/api/v1/system/status", response_model=SystemStatus)
async def system_status(request: Request) -> SystemStatus:
    container: Container = request.app.state.container
    settings = container.settings
    limiters = [await limiter.usage() for limiter in container.limiters.values()]
    return SystemStatus(
        cache_backend="redis" if settings.redis_url else "memory",
        providers=[
            ProviderStatus(name="finnhub", configured=settings.finnhub_api_key is not None),
            ProviderStatus(name="twelvedata", configured=settings.twelvedata_api_key is not None),
            ProviderStatus(name="fred", configured=settings.fred_api_key is not None),
        ],
        limiters=[LimiterStatus.model_validate(u, from_attributes=True) for u in limiters],
    )

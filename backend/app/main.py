import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import system
from app.container import build_container
from app.core.config import Settings, get_settings
from app.core.errors import NoDataError, ProviderError, ProviderUnavailable, RateLimitExceeded
from app.core.logging import configure_logging

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.secret_values())

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.container = build_container(settings)
        try:
            yield
        finally:
            await app.state.container.close()

    app = FastAPI(title="MarketPulse API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(system.router)

    # Provider failures reach here only when there's no cached copy to fall back on.
    @app.exception_handler(ProviderError)
    async def provider_error_handler(request: Request, exc: ProviderError) -> JSONResponse:
        if isinstance(exc, NoDataError):
            status, message = 404, "No data available for this request."
        elif isinstance(exc, ProviderUnavailable):
            status, message = 503, "This data isn't available from our data providers right now."
        elif isinstance(exc, RateLimitExceeded):
            status, message = 503, "We're fetching a lot of data right now. Please try again in a minute."
        else:
            status, message = 502, "Our data provider is having trouble. Please try again shortly."
        logger.warning("Provider error on %s %s: %s", request.method, request.url.path, exc)
        return JSONResponse(status_code=status, content={"detail": message, "provider": exc.provider})

    return app


app = create_app()

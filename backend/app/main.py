import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import auth, markets, portfolio, stocks, stream, system
from app.container import build_container
from app.core.config import Settings, get_settings
from app.core.errors import (
    AppError,
    NoDataError,
    ProviderError,
    ProviderUnavailable,
    RateLimitExceeded,
    SymbolNotFound,
)
from app.core.logging import configure_logging
from app.jobs.scheduler import build_scheduler

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.secret_values())

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        container = build_container(settings)
        app.state.container = container
        container.start_streaming()
        scheduler = build_scheduler(container) if settings.enable_background_jobs else None
        if scheduler is not None:
            scheduler.start()
        try:
            yield
        finally:
            if scheduler is not None:
                scheduler.shutdown(wait=False)
            await container.close()

    app = FastAPI(title="MarketPulse API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(system.router)
    app.include_router(markets.router)
    app.include_router(stocks.router)
    app.include_router(stream.router)
    app.include_router(auth.router)
    app.include_router(portfolio.router)

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content={"detail": exc.message, "code": exc.code})

    @app.exception_handler(SymbolNotFound)
    async def symbol_not_found_handler(request: Request, exc: SymbolNotFound) -> JSONResponse:
        return JSONResponse(
            status_code=404, content={"detail": f"We couldn't find {exc.symbol}.", "code": "not_found"}
        )

    # Provider failures reach here only when there's no cached copy to fall back on.
    @app.exception_handler(ProviderError)
    async def provider_error_handler(request: Request, exc: ProviderError) -> JSONResponse:
        # `code` lets the UI tell "not on our data plan" apart from a temporary failure worth retrying.
        if isinstance(exc, NoDataError):
            status, code, message = 404, "no_data", "No data available for this request."
        elif isinstance(exc, ProviderUnavailable):
            status, code, message = 503, "unavailable", "This data isn't available on our current data plan."
        elif isinstance(exc, RateLimitExceeded):
            status, code = 503, "rate_limited"
            message = "We're fetching a lot of data right now. Please try again in a minute."
        else:
            status, code, message = (
                502,
                "provider_error",
                "Our data provider is having trouble. Please try again.",
            )
        logger.warning("Provider error on %s %s: %s", request.method, request.url.path, exc)
        return JSONResponse(
            status_code=status, content={"detail": message, "code": code, "provider": exc.provider}
        )

    return app


app = create_app()

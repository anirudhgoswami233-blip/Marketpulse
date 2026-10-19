from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import ContainerDep, SessionDep, SymbolDep
from app.container import Container
from app.core.cache import Fetched
from app.models import Symbol
from app.providers.base import CompanyProfile, KeyMetrics, NewsItem, Quote
from app.schemas.markets import ChartOut, SearchResults, SymbolOut
from app.services import quote_service, search_service, stock_service
from app.services.stock_service import ChartRange

router = APIRouter(prefix="/api/v1", tags=["stocks"])


def forex_board_max_age(container: Container) -> timedelta:
    # A board rate is good enough for a page view while it's younger than one refresh interval.
    return timedelta(seconds=container.settings.forex_refresh_s)


def to_symbol_out(symbol: Symbol) -> SymbolOut:
    return SymbolOut(
        symbol=symbol.symbol,
        display_symbol=symbol.display_symbol,
        description=symbol.description,
        exchange=symbol.exchange_code,
        type=symbol.type,
        currency=symbol.currency,
        price_available=search_service.price_available(symbol),
        streamable=search_service.streamable(symbol),
        tradable=search_service.tradable(symbol),
        price_note=search_service.price_note(symbol),
        trade_note=search_service.trade_note(symbol),
        quote_delay_min=search_service.FOREX_QUOTE_DELAY_MIN if search_service.is_forex(symbol) else None,
    )


@router.get("/search", response_model=SearchResults)
async def search(
    session: SessionDep,
    q: Annotated[str, Query(min_length=1, max_length=64)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> SearchResults:
    results = await search_service.search_symbols(session, q, limit)
    return SearchResults(query=q, results=[to_symbol_out(s) for s in results])


@router.get("/stocks/{symbol}", response_model=SymbolOut)
async def stock(symbol: SymbolDep) -> SymbolOut:
    return to_symbol_out(symbol)


@router.get("/stocks/{symbol}/quote", response_model=Fetched[Quote])
async def quote(symbol: SymbolDep, container: ContainerDep) -> Fetched[Quote]:
    return await quote_service.get_symbol_quote(
        container.providers, container.hub, container.cache, symbol, forex_board_max_age(container)
    )


@router.get("/stocks/{symbol}/profile", response_model=Fetched[CompanyProfile])
async def profile(symbol: SymbolDep, container: ContainerDep) -> Fetched[CompanyProfile]:
    return await stock_service.get_profile(container.providers.reference, symbol)


@router.get("/stocks/{symbol}/metrics", response_model=Fetched[KeyMetrics])
async def metrics(symbol: SymbolDep, container: ContainerDep) -> Fetched[KeyMetrics]:
    return await stock_service.get_metrics(container.providers.reference, symbol)


@router.get("/stocks/{symbol}/news", response_model=Fetched[list[NewsItem]])
async def news(symbol: SymbolDep, container: ContainerDep) -> Fetched[list[NewsItem]]:
    return await stock_service.get_news(container.providers.news, symbol)


@router.get("/stocks/{symbol}/chart", response_model=Fetched[ChartOut])
async def chart(
    symbol: SymbolDep,
    container: ContainerDep,
    session: SessionDep,
    range: Annotated[ChartRange, Query()] = ChartRange.M1,
) -> Fetched[ChartOut]:
    return await stock_service.get_chart(session, container.providers.history, container.cache, symbol, range)

import asyncio
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query, status
from sqlalchemy import select

from app.api.deps import ContainerDep, CurrentUser, SessionDep
from app.api.stocks import to_symbol_out
from app.core.errors import NoDataError, ProviderError, ProviderUnavailable
from app.models import Symbol, Trade
from app.schemas.portfolio import (
    BulkQuotes,
    OrderIn,
    PortfolioOut,
    PositionOut,
    QuoteResult,
    TradeOut,
    WatchlistCreate,
    WatchlistItemCreate,
    WatchlistOut,
)
from app.services import quote_service, trading_service, watchlist_service
from app.services.portfolio_math import q
from app.services.search_service import price_available, resolve_symbol
from app.services.trading_service import PortfolioView, Side
from app.services.watchlist_service import WatchlistView

router = APIRouter(prefix="/api/v1", tags=["portfolio"])

MAX_BULK_SYMBOLS = 50
BULK_CONCURRENCY = 5


def _watchlist_out(view: WatchlistView) -> WatchlistOut:
    w = view.watchlist
    return WatchlistOut(
        id=w.id, name=w.name, created_at=w.created_at, symbols=[to_symbol_out(s) for s in view.symbols]
    )


@router.get("/watchlists", response_model=list[WatchlistOut])
async def list_watchlists(user: CurrentUser, session: SessionDep) -> list[WatchlistOut]:
    return [_watchlist_out(v) for v in await watchlist_service.list_watchlists(session, user.id)]


@router.post("/watchlists", response_model=WatchlistOut, status_code=status.HTTP_201_CREATED)
async def create_watchlist(
    body: WatchlistCreate, user: CurrentUser, session: SessionDep, container: ContainerDep
) -> WatchlistOut:
    watchlist = await watchlist_service.create_watchlist(session, container.settings, user.id, body.name)
    return _watchlist_out(WatchlistView(watchlist, []))


@router.patch("/watchlists/{watchlist_id}", response_model=WatchlistOut)
async def rename_watchlist(
    watchlist_id: int, body: WatchlistCreate, user: CurrentUser, session: SessionDep
) -> WatchlistOut:
    await watchlist_service.rename_watchlist(session, user.id, watchlist_id, body.name)
    return _watchlist_out(await watchlist_service.get_watchlist(session, user.id, watchlist_id))


@router.delete("/watchlists/{watchlist_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_watchlist(watchlist_id: int, user: CurrentUser, session: SessionDep) -> None:
    await watchlist_service.delete_watchlist(session, user.id, watchlist_id)


@router.post(
    "/watchlists/{watchlist_id}/items", response_model=WatchlistOut, status_code=status.HTTP_201_CREATED
)
async def add_watchlist_item(
    watchlist_id: int,
    body: WatchlistItemCreate,
    user: CurrentUser,
    session: SessionDep,
    container: ContainerDep,
) -> WatchlistOut:
    await watchlist_service.add_symbol(session, container.settings, user.id, watchlist_id, body.symbol)
    return _watchlist_out(await watchlist_service.get_watchlist(session, user.id, watchlist_id))


@router.delete("/watchlists/{watchlist_id}/items/{symbol}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_watchlist_item(
    watchlist_id: int, symbol: str, user: CurrentUser, session: SessionDep
) -> None:
    await watchlist_service.remove_symbol(session, user.id, watchlist_id, symbol)


@router.get("/quotes", response_model=BulkQuotes)
async def bulk_quotes(
    container: ContainerDep, session: SessionDep, symbols: Annotated[str, Query(max_length=2048)]
) -> BulkQuotes:
    """Quotes for several symbols (watchlists, portfolio), each served from the 60s quote cache when warm."""
    requested = list(dict.fromkeys(s.strip().upper() for s in symbols.split(",") if s.strip()))[
        :MAX_BULK_SYMBOLS
    ]
    rows = (await session.execute(select(Symbol).where(Symbol.symbol.in_(requested)))).scalars().all()
    by_symbol: dict[str, Symbol] = {}
    for row in rows:  # prefer US listings, as resolve_symbol does
        if row.symbol not in by_symbol or row.exchange_code == "US":
            by_symbol[row.symbol] = row
    semaphore = asyncio.Semaphore(BULK_CONCURRENCY)

    async def one(code: str) -> QuoteResult:
        symbol = by_symbol.get(code)
        if symbol is None:
            return QuoteResult(symbol=code, quote=None, error="not_found")
        if not price_available(symbol):
            return QuoteResult(symbol=code, quote=None, error="unavailable")
        try:
            async with semaphore:
                quote = await quote_service.get_quote(container.providers.quotes, container.hub, symbol)
        except (ProviderUnavailable, NoDataError):
            return QuoteResult(symbol=code, quote=None, error="unavailable")
        except ProviderError:
            return QuoteResult(symbol=code, quote=None, error="provider_error")
        return QuoteResult(symbol=code, quote=quote)

    return BulkQuotes(results=list(await asyncio.gather(*(one(c) for c in requested))))


def _portfolio_out(view: PortfolioView) -> PortfolioOut:
    p, totals = view.portfolio, view.totals
    return PortfolioOut(
        id=p.id,
        name=p.name,
        base_currency=p.base_currency,
        starting_cash=p.starting_cash,
        cash=totals.cash,
        market_value=totals.market_value,
        equity=totals.equity,
        total_return=totals.total_return,
        total_return_pct=totals.total_return_pct,
        realized_pnl=view.realized_pnl,
        positions=[
            PositionOut(
                symbol=pos.symbol.symbol,
                display_symbol=pos.symbol.display_symbol,
                description=pos.symbol.description,
                quantity=pos.holding.quantity,
                avg_cost=pos.holding.avg_cost,
                currency=pos.currency,
                last_price=pos.last_price,
                price_as_of=pos.price_as_of,
                price_stale=pos.price_stale,
                market_value=pos.valuation.market_value if pos.valuation else None,
                cost_basis=pos.holding.quantity * pos.holding.avg_cost,
                unrealized_pnl=pos.valuation.unrealized_pnl if pos.valuation else None,
                unrealized_pnl_pct=pos.valuation.unrealized_pnl_pct if pos.valuation else None,
            )
            for pos in view.positions
        ],
        incomplete=view.incomplete,
        as_of=datetime.now(UTC),
    )


@router.get("/portfolio", response_model=PortfolioOut)
async def get_portfolio(user: CurrentUser, session: SessionDep, container: ContainerDep) -> PortfolioOut:
    portfolio = await trading_service.get_portfolio(session, user.id)
    view = await trading_service.value_portfolio(
        session, container.providers.quotes, container.hub, portfolio
    )
    return _portfolio_out(view)


@router.post("/portfolio/orders", response_model=TradeOut, status_code=status.HTTP_201_CREATED)
async def place_order(
    body: OrderIn, user: CurrentUser, session: SessionDep, container: ContainerDep
) -> TradeOut:
    symbol = await resolve_symbol(session, body.symbol)
    quantity = trading_service.parse_quantity(body.quantity)
    trade = await trading_service.place_order(
        session, container.providers.quotes, container.hub, user.id, symbol, Side(body.side), quantity
    )
    return _trade_out(trade, symbol)


@router.get("/portfolio/trades", response_model=list[TradeOut])
async def list_trades(
    user: CurrentUser, session: SessionDep, limit: Annotated[int, Query(ge=1, le=500)] = 100
) -> list[TradeOut]:
    portfolio = await trading_service.get_portfolio(session, user.id)
    return [_trade_out(t, s) for t, s in await trading_service.list_trades(session, portfolio, limit)]


@router.post("/portfolio/reset", response_model=PortfolioOut)
async def reset_portfolio(user: CurrentUser, session: SessionDep, container: ContainerDep) -> PortfolioOut:
    portfolio = await trading_service.reset_portfolio(session, user.id)
    view = await trading_service.value_portfolio(
        session, container.providers.quotes, container.hub, portfolio
    )
    return _portfolio_out(view)


def _trade_out(trade: Trade, symbol: Symbol) -> TradeOut:
    return TradeOut(
        id=trade.id,
        symbol=symbol.symbol,
        display_symbol=symbol.display_symbol,
        side=Side(trade.side).value,
        quantity=trade.quantity,
        price=trade.price,
        currency=trade.currency,
        notional=q(trade.quantity * trade.price),
        realized_pnl=trade.realized_pnl,
        executed_at=trade.executed_at,
        price_as_of=trade.price_as_of,
    )

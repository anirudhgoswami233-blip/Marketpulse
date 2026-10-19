"""Paper-trading orders and portfolio valuation.

Orders are market orders filled at the current quote (REST snapshot overlaid with the latest live trade).
Money math is Decimal in Python; the portfolio row's `version` makes concurrent orders safe on both SQLite
(no row locks) and PostgreSQL: an order commits only if nobody else changed the portfolio since we read it.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, NotFound, ProviderError, ValidationFailed
from app.models import Portfolio, Position, Symbol, Trade
from app.providers.base import MarketDataProvider, Quote
from app.services import quote_service
from app.services.portfolio_math import (
    ZERO,
    Holding,
    PortfolioTotals,
    Valuation,
    apply_buy,
    apply_sell,
    portfolio_totals,
    q,
    value_holding,
)
from app.services.search_service import trade_note
from app.ws.hub import PriceHub

logger = logging.getLogger(__name__)

MAX_ORDER_ATTEMPTS = 3
MAX_QUANTITY = Decimal("1000000000")
QUANTITY_PLACES = 6
VALUATION_CONCURRENCY = 5


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"


class PriceUnavailable(AppError):
    status, code = 503, "price_unavailable"


class ConcurrentUpdate(AppError):
    status, code = 409, "concurrent_update"


def parse_quantity(raw: Decimal | str) -> Decimal:
    try:
        quantity = Decimal(raw)
    except (InvalidOperation, ValueError) as exc:
        raise ValidationFailed("Enter a valid quantity.", code="invalid_quantity") from exc
    if not quantity.is_finite() or quantity <= 0 or quantity > MAX_QUANTITY:
        raise ValidationFailed("Quantity must be greater than zero.", code="invalid_quantity")
    exponent = quantity.normalize().as_tuple().exponent
    if isinstance(exponent, int) and -exponent > QUANTITY_PLACES:
        raise ValidationFailed(
            f"Quantity can have at most {QUANTITY_PLACES} decimal places.", code="invalid_quantity"
        )
    return quantity


async def get_portfolio(session: AsyncSession, user_id: int, portfolio_id: int | None = None) -> Portfolio:
    stmt = select(Portfolio).where(Portfolio.user_id == user_id)
    stmt = stmt.where(Portfolio.id == portfolio_id) if portfolio_id else stmt.order_by(Portfolio.id)
    portfolio = (await session.execute(stmt.limit(1))).scalar_one_or_none()
    if portfolio is None:
        raise NotFound("Portfolio not found.")
    return portfolio


async def place_order(
    session: AsyncSession,
    provider: MarketDataProvider,
    hub: PriceHub,
    user_id: int,
    symbol: Symbol,
    side: Side,
    quantity: Decimal,
    portfolio_id: int | None = None,
) -> Trade:
    note = trade_note(symbol)
    if note is not None:
        raise ValidationFailed(f"{symbol.display_symbol} can't be traded. {note}", code="not_tradable")

    try:
        fetched = await quote_service.get_quote(provider, hub, symbol)
    except ProviderError as exc:
        raise PriceUnavailable("We couldn't get a current price. Please try again in a moment.") from exc
    if fetched.stale:
        raise PriceUnavailable(
            "Prices are delayed right now, so orders are paused. Please try again shortly."
        )
    quote = fetched.data

    for attempt in range(1, MAX_ORDER_ATTEMPTS + 1):
        portfolio = await get_portfolio(session, user_id, portfolio_id)
        currency = symbol.currency or portfolio.base_currency
        if currency != portfolio.base_currency:
            raise ValidationFailed(
                f"Only {portfolio.base_currency} securities can be traded in this portfolio.", code="currency"
            )
        target_id = portfolio.id
        try:
            trade = await _execute(
                session, portfolio, symbol, side, quantity, quote, fetched.as_of, fetched.source
            )
        except ConcurrentUpdate:
            # Rollback expires every loaded object; reload explicitly (lazy loads can't run in async code).
            await session.rollback()
            await session.refresh(symbol)
            logger.info("Order for portfolio %s hit a concurrent update (attempt %d)", target_id, attempt)
            continue
        await session.commit()
        logger.info(
            "Filled %s %s %s @ %s for portfolio %s", side, quantity, symbol.symbol, trade.price, target_id
        )
        return trade
    raise ConcurrentUpdate("Your portfolio changed while placing this order. Please try again.")


async def _execute(
    session: AsyncSession,
    portfolio: Portfolio,
    symbol: Symbol,
    side: Side,
    quantity: Decimal,
    quote: Quote,
    as_of: datetime,
    source: str,
) -> Trade:
    position = await session.get(Position, (portfolio.id, symbol.id))
    holding = Holding(position.quantity, position.avg_cost) if position else Holding(ZERO, ZERO)
    price = quote.price
    notional = q(quantity * price)
    realized: Decimal | None = None

    if side is Side.BUY:
        if notional > portfolio.cash:
            raise ValidationFailed(
                f"Not enough cash: this order costs {notional:,.2f} {portfolio.base_currency} "
                f"and you have {portfolio.cash:,.2f}.",
                code="insufficient_cash",
            )
        new_holding = apply_buy(holding, quantity, price)
        new_cash = portfolio.cash - notional
    else:
        if quantity > holding.quantity:
            raise ValidationFailed(
                f"You can sell at most {holding.quantity.normalize():f} shares of {symbol.display_symbol}.",
                code="insufficient_shares",
            )
        new_holding, realized = apply_sell(holding, quantity, price)
        new_cash = portfolio.cash + notional

    # Optimistic concurrency: only succeeds if the portfolio is unchanged since we read it.
    result = await session.execute(
        update(Portfolio)
        .where(Portfolio.id == portfolio.id, Portfolio.version == portfolio.version)
        .values(cash=q(new_cash), version=portfolio.version + 1)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:  # type: ignore[attr-defined]
        raise ConcurrentUpdate("portfolio changed")

    if new_holding.quantity == 0:
        if position is not None:
            await session.delete(position)
    elif position is None:
        session.add(
            Position(
                portfolio_id=portfolio.id,
                symbol_id=symbol.id,
                quantity=new_holding.quantity,
                avg_cost=new_holding.avg_cost,
                currency=portfolio.base_currency,
            )
        )
    else:
        position.quantity = new_holding.quantity
        position.avg_cost = new_holding.avg_cost

    trade = Trade(
        portfolio_id=portfolio.id,
        symbol_id=symbol.id,
        side=side.value,
        quantity=quantity,
        price=price,
        currency=portfolio.base_currency,
        realized_pnl=realized,
        executed_at=datetime.now(UTC),
        price_source=source,
        price_as_of=as_of,
    )
    session.add(trade)
    await session.flush()
    return trade


async def reset_portfolio(session: AsyncSession, user_id: int, portfolio_id: int | None = None) -> Portfolio:
    portfolio = await get_portfolio(session, user_id, portfolio_id)
    await session.execute(delete(Trade).where(Trade.portfolio_id == portfolio.id))
    await session.execute(delete(Position).where(Position.portfolio_id == portfolio.id))
    portfolio.cash = portfolio.starting_cash
    portfolio.version += 1
    await session.commit()
    logger.info("Reset portfolio %s", portfolio.id)
    return portfolio


@dataclass(frozen=True)
class PositionView:
    symbol: Symbol
    holding: Holding
    currency: str
    last_price: Decimal | None
    price_as_of: datetime | None
    price_stale: bool
    valuation: Valuation | None


@dataclass(frozen=True)
class PortfolioView:
    portfolio: Portfolio
    positions: list[PositionView]
    totals: PortfolioTotals
    realized_pnl: Decimal
    # True when any position couldn't be priced; totals then use cost basis for those positions.
    incomplete: bool


async def value_portfolio(
    session: AsyncSession, provider: MarketDataProvider, hub: PriceHub, portfolio: Portfolio
) -> PortfolioView:
    rows = (
        await session.execute(
            select(Position, Symbol)
            .join(Symbol, Symbol.id == Position.symbol_id)
            .where(Position.portfolio_id == portfolio.id)
            .order_by(Symbol.symbol)
        )
    ).all()
    semaphore = asyncio.Semaphore(VALUATION_CONCURRENCY)

    async def view(position: Position, symbol: Symbol) -> PositionView:
        holding = Holding(position.quantity, position.avg_cost)
        try:
            async with semaphore:
                fetched = await quote_service.get_quote(provider, hub, symbol)
        except ProviderError as exc:
            logger.warning("Valuation: no price for %s: %s", symbol.symbol, exc)
            return PositionView(symbol, holding, position.currency, None, None, True, None)
        price = fetched.data.price
        return PositionView(
            symbol,
            holding,
            position.currency,
            price,
            fetched.as_of,
            fetched.stale,
            value_holding(holding, price),
        )

    positions = list(await asyncio.gather(*(view(p, s) for p, s in rows)))
    market_values = [
        p.valuation.market_value if p.valuation else q(p.holding.quantity * p.holding.avg_cost)
        for p in positions
    ]
    realized = sum(
        (
            r
            for r in (
                await session.execute(
                    select(Trade.realized_pnl).where(
                        Trade.portfolio_id == portfolio.id, Trade.realized_pnl.is_not(None)
                    )
                )
            ).scalars()
            if r is not None
        ),
        ZERO,
    )
    return PortfolioView(
        portfolio=portfolio,
        positions=positions,
        totals=portfolio_totals(portfolio.cash, portfolio.starting_cash, market_values),
        realized_pnl=q(realized),
        incomplete=any(p.valuation is None for p in positions),
    )


async def list_trades(
    session: AsyncSession, portfolio: Portfolio, limit: int = 100
) -> list[tuple[Trade, Symbol]]:
    rows = await session.execute(
        select(Trade, Symbol)
        .join(Symbol, Symbol.id == Trade.symbol_id)
        .where(Trade.portfolio_id == portfolio.id)
        .order_by(Trade.executed_at.desc(), Trade.id.desc())
        .limit(limit)
    )
    return [(t, s) for t, s in rows.all()]

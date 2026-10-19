"""Pure Decimal arithmetic for paper trading: cost basis, realized and unrealized P&L. No I/O."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal

MONEY_PLACES = Decimal("0.000001")  # storage precision (Numeric(20, 6))
ZERO = Decimal(0)


def q(value: Decimal) -> Decimal:
    return value.quantize(MONEY_PLACES, rounding=ROUND_HALF_EVEN)


@dataclass(frozen=True)
class Holding:
    quantity: Decimal
    avg_cost: Decimal


def apply_buy(holding: Holding, quantity: Decimal, price: Decimal, fee: Decimal = ZERO) -> Holding:
    """Weighted-average cost basis; fees are part of the cost."""
    total_qty = holding.quantity + quantity
    total_cost = holding.quantity * holding.avg_cost + quantity * price + fee
    return Holding(quantity=total_qty, avg_cost=q(total_cost / total_qty))


def apply_sell(
    holding: Holding, quantity: Decimal, price: Decimal, fee: Decimal = ZERO
) -> tuple[Holding, Decimal]:
    """Returns the remaining holding and the realized P&L. Average cost doesn't change on a sell."""
    if quantity > holding.quantity:
        raise ValueError("cannot sell more than held")
    realized = q((price - holding.avg_cost) * quantity - fee)
    remaining = holding.quantity - quantity
    return Holding(quantity=remaining, avg_cost=holding.avg_cost if remaining else ZERO), realized


@dataclass(frozen=True)
class Valuation:
    market_value: Decimal
    cost_basis: Decimal
    unrealized_pnl: Decimal
    unrealized_pnl_pct: Decimal | None


def value_holding(holding: Holding, last_price: Decimal) -> Valuation:
    market_value = q(holding.quantity * last_price)
    cost_basis = q(holding.quantity * holding.avg_cost)
    pnl = market_value - cost_basis
    pct = q(pnl / cost_basis * 100) if cost_basis else None
    return Valuation(market_value, cost_basis, pnl, pct)


@dataclass(frozen=True)
class PortfolioTotals:
    cash: Decimal
    market_value: Decimal
    equity: Decimal
    total_return: Decimal
    total_return_pct: Decimal | None


def portfolio_totals(cash: Decimal, starting_cash: Decimal, market_values: list[Decimal]) -> PortfolioTotals:
    market_value = sum(market_values, ZERO)
    equity = cash + market_value
    total_return = equity - starting_cash
    pct = q(total_return / starting_cash * 100) if starting_cash else None
    return PortfolioTotals(q(cash), q(market_value), q(equity), q(total_return), pct)

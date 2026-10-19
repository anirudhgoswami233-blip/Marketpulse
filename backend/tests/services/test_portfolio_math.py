from decimal import Decimal as D

import pytest

from app.services.portfolio_math import Holding, apply_buy, apply_sell, portfolio_totals, value_holding

EMPTY = Holding(D(0), D(0))


def test_weighted_average_cost() -> None:
    h = apply_buy(EMPTY, D(10), D("100"))
    h = apply_buy(h, D(5), D("130"))
    assert h.quantity == D(15)
    assert h.avg_cost == D("110.000000")


def test_fees_are_part_of_cost_basis() -> None:
    h = apply_buy(EMPTY, D(4), D("25"), fee=D("1"))
    assert h.avg_cost == D("25.250000")


def test_fractional_shares_keep_precision() -> None:
    h = apply_buy(EMPTY, D("0.333333"), D("300"))
    h = apply_buy(h, D("0.666667"), D("303"))
    assert h.quantity == D("1.000000")
    assert h.avg_cost == D("302.000001")  # rounded half-even at 6 places


def test_sell_realizes_pnl_and_keeps_average() -> None:
    h = apply_buy(EMPTY, D(10), D("100"))
    remaining, realized = apply_sell(h, D(4), D("120"))
    assert realized == D("80.000000")
    assert remaining == Holding(D(6), D("100"))


def test_selling_everything_resets_average() -> None:
    h = apply_buy(EMPTY, D(2), D("50"))
    remaining, realized = apply_sell(h, D(2), D("45"))
    assert remaining == Holding(D(0), D(0))
    assert realized == D("-10.000000")


def test_cannot_oversell() -> None:
    with pytest.raises(ValueError):
        apply_sell(Holding(D(1), D(10)), D(2), D(10))


def test_valuation_and_totals() -> None:
    valuation = value_holding(Holding(D(10), D("100")), D("90"))
    assert valuation.market_value == D("900.000000")
    assert valuation.unrealized_pnl == D("-100.000000")
    assert valuation.unrealized_pnl_pct == D("-10.000000")

    totals = portfolio_totals(D("99000"), D("100000"), [valuation.market_value])
    assert totals.equity == D("99900.000000")
    assert totals.total_return == D("-100.000000")
    assert totals.total_return_pct == D("-0.100000")

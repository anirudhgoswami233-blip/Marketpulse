"""Cross rates from a few USD pairs. Pure Decimal math, no I/O.

Every currency (and metal) is expressed as "USD per one unit". A cross A/B is then usd(A) / usd(B), so
nine fetched pairs price every combination on the board and in the converter.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

RATE_PLACES = Decimal("1e-8")
PCT_PLACES = Decimal("0.0001")


@dataclass(frozen=True)
class PairQuote:
    rate: Decimal
    prev_close: Decimal | None


@dataclass(frozen=True)
class UsdValue:
    now: Decimal
    prev: Decimal | None


def split_pair(pair: str) -> tuple[str, str]:
    base, _, quote = pair.partition("/")
    if len(base) != 3 or len(quote) != 3:
        raise ValueError(f"not a currency pair: {pair!r}")
    return base.upper(), quote.upper()


def usd_values(quotes: Mapping[str, PairQuote]) -> dict[str, UsdValue]:
    """`quotes` are pairs with USD on one side, e.g. {"EUR/USD": ..., "USD/JPY": ...}."""
    values = {"USD": UsdValue(Decimal(1), Decimal(1))}
    for pair, quote in quotes.items():
        base, counter = split_pair(pair)
        if quote.rate <= 0:
            continue
        if counter == "USD":
            values[base] = UsdValue(quote.rate, quote.prev_close)
        elif base == "USD":
            prev = 1 / quote.prev_close if quote.prev_close else None
            values[counter] = UsdValue(1 / quote.rate, prev)
    return values


@dataclass(frozen=True)
class CrossRate:
    pair: str
    rate: Decimal
    change_pct: Decimal | None


def cross(pair: str, values: Mapping[str, UsdValue]) -> CrossRate | None:
    base, counter = split_pair(pair)
    if base not in values or counter not in values:
        return None
    a, b = values[base], values[counter]
    try:
        rate = (a.now / b.now).quantize(RATE_PLACES)
        change = None
        if a.prev and b.prev:
            prev = a.prev / b.prev
            change = ((a.now / b.now - prev) / prev * 100).quantize(PCT_PLACES)
    except (InvalidOperation, ZeroDivisionError):
        return None
    return CrossRate(pair, rate, change)


def convert(amount: Decimal, source: str, target: str, values: Mapping[str, UsdValue]) -> Decimal | None:
    if source not in values or target not in values:
        return None
    return (amount * values[source].now / values[target].now).quantize(RATE_PLACES)

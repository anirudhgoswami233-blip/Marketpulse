"""Technical indicators over daily closes/volumes. Pure functions, no I/O.

Definitions (keep them exactly like this so results are reproducible and testable):
- SMA(n): mean of the last n values.
- EMA(n): alpha = 2/(n+1), seeded with the SMA of the first n values.
- RSI(14): Wilder's smoothing; seeded with the simple average of the first 14 gains/losses.
- MACD: EMA(12) - EMA(26); signal = EMA(9) of MACD; histogram = MACD - signal.

Series functions return a list aligned with the input, with None where there isn't enough data yet.
Indicator math uses float: these are statistics for labels, not money.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

Series = list[float | None]


def sma(values: Sequence[float], n: int) -> Series:
    if n <= 0:
        raise ValueError("n must be positive")
    out: Series = [None] * len(values)
    window_sum = 0.0
    for i, value in enumerate(values):
        window_sum += value
        if i >= n:
            window_sum -= values[i - n]
        if i >= n - 1:
            out[i] = window_sum / n
    return out


def ema(values: Sequence[float], n: int) -> Series:
    if n <= 0:
        raise ValueError("n must be positive")
    out: Series = [None] * len(values)
    if len(values) < n:
        return out
    alpha = 2 / (n + 1)
    current = sum(values[:n]) / n
    out[n - 1] = current
    for i in range(n, len(values)):
        current = alpha * values[i] + (1 - alpha) * current
        out[i] = current
    return out


def _ema_of_partial(values: Series, n: int) -> Series:
    """EMA over a series that starts with Nones (e.g. MACD), seeded once n real values exist."""
    out: Series = [None] * len(values)
    start = next((i for i, v in enumerate(values) if v is not None), None)
    if start is None:
        return out
    real = [v for v in values[start:] if v is not None]
    for offset, value in enumerate(ema(real, n)):
        out[start + offset] = value
    return out


def rsi(closes: Sequence[float], n: int = 14) -> Series:
    out: Series = [None] * len(closes)
    if len(closes) <= n:
        return out
    gains = [max(closes[i] - closes[i - 1], 0.0) for i in range(1, len(closes))]
    losses = [max(closes[i - 1] - closes[i], 0.0) for i in range(1, len(closes))]
    avg_gain = sum(gains[:n]) / n
    avg_loss = sum(losses[:n]) / n
    out[n] = _rsi_value(avg_gain, avg_loss)
    for i in range(n, len(gains)):
        avg_gain = (avg_gain * (n - 1) + gains[i]) / n
        avg_loss = (avg_loss * (n - 1) + losses[i]) / n
        out[i + 1] = _rsi_value(avg_gain, avg_loss)
    return out


def _rsi_value(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0:
        return 50.0 if avg_gain == 0 else 100.0  # flat prices are neutral, not "overbought"
    return 100 - 100 / (1 + avg_gain / avg_loss)


@dataclass(frozen=True)
class Macd:
    macd: Series
    signal: Series
    histogram: Series


def macd(closes: Sequence[float], fast: int = 12, slow: int = 26, signal_n: int = 9) -> Macd:
    fast_ema, slow_ema = ema(closes, fast), ema(closes, slow)
    line: Series = [
        f - s if f is not None and s is not None else None for f, s in zip(fast_ema, slow_ema, strict=True)
    ]
    signal = _ema_of_partial(line, signal_n)
    histogram: Series = [
        m - s if m is not None and s is not None else None for m, s in zip(line, signal, strict=True)
    ]
    return Macd(line, signal, histogram)


def bars_since_sign_change(series: Series, within: int) -> tuple[int, int] | None:
    """If `series` changed sign within the last `within` steps, return (bars_ago, new_sign)."""
    tail = series[-(within + 1) :]
    for back in range(len(tail) - 1):
        cur, prev = tail[-1 - back], tail[-2 - back]
        if cur is None or prev is None:
            return None
        if cur > 0 >= prev:
            return back, 1
        if cur < 0 <= prev:
            return back, -1
    return None


def average(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None

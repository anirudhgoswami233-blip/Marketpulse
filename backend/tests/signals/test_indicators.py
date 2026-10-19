import math

import pytest

from app.signals import indicators as ind

# Closes from Wilder's RSI worked example (StockCharts ChartSchool). The article prints 70.53, 66.32, ...;
# it rounds intermediate averages. Exact arithmetic gives the values below (about 0.07 lower), e.g. the
# first RSI = 100 - 100 / (1 + 3.34 / 1.40) = 70.46 (14-day gain sum 3.34, loss sum 1.40).
WILDER_CLOSES = [
    44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08,
    45.89, 46.03, 45.61, 46.28, 46.28, 46.00, 46.03, 46.41, 46.22,
]  # fmt: skip
WILDER_RSI = {14: 70.46, 15: 66.25, 16: 66.48, 17: 69.35, 18: 66.29}


def test_sma() -> None:
    assert ind.sma([1, 2, 3, 4, 5], 3) == [None, None, 2.0, 3.0, 4.0]
    assert ind.sma([1, 2], 3) == [None, None]
    with pytest.raises(ValueError):
        ind.sma([1], 0)


def test_ema_is_seeded_with_sma() -> None:
    # alpha = 2/(3+1) = 0.5; seed = mean(1,2,3) = 2
    assert ind.ema([1, 2, 3, 4, 5, 6], 3) == [None, None, 2.0, 3.0, 4.0, 5.0]
    assert ind.ema([1, 2], 3) == [None, None]


def test_rsi_matches_wilder_reference() -> None:
    values = ind.rsi(WILDER_CLOSES, 14)
    assert values[14] == pytest.approx(100 - 100 / (1 + 3.34 / 1.40), abs=1e-6)
    assert all(v is None for v in values[:14])
    for index, expected in WILDER_RSI.items():
        value = values[index]
        assert value is not None
        assert value == pytest.approx(expected, abs=0.01)


def test_rsi_edge_cases() -> None:
    assert ind.rsi([10.0] * 20)[-1] == 50.0  # flat: neutral, no division by zero
    assert ind.rsi([float(i) for i in range(20)])[-1] == 100.0  # only gains
    assert ind.rsi([float(20 - i) for i in range(20)])[-1] == 0.0  # only losses
    assert ind.rsi([1.0] * 14) == [None] * 14  # not enough data


def test_macd_alignment_and_values() -> None:
    closes = [100 + math.sin(i / 5) * 5 for i in range(60)]
    result = ind.macd(closes)
    # MACD exists from the 26th value; the signal needs 9 MACD values more.
    assert result.macd[24] is None and result.macd[25] is not None
    assert result.signal[32] is None and result.signal[33] is not None
    fast, slow = ind.ema(closes, 12)[-1], ind.ema(closes, 26)[-1]
    assert fast is not None and slow is not None
    assert result.macd[-1] == pytest.approx(fast - slow)
    hist, macd_last, signal_last = result.histogram[-1], result.macd[-1], result.signal[-1]
    assert hist is not None and macd_last is not None and signal_last is not None
    assert hist == pytest.approx(macd_last - signal_last)


def test_sign_change_detection() -> None:
    assert ind.bars_since_sign_change([-2.0, -1.0, 0.5], within=3) == (0, 1)
    assert ind.bars_since_sign_change([1.0, -1.0, -2.0, -3.0], within=3) == (2, -1)
    assert ind.bars_since_sign_change([1.0, -1.0, -2.0, -3.0, -4.0], within=3) is None  # too long ago
    assert ind.bars_since_sign_change([None, 1.0], within=3) is None

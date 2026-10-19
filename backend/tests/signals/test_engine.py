from app.signals import engine
from app.signals import indicators as ind
from app.signals.engine import DailyBar, Label, Signal, Skipped
from app.signals.sentiment import news_tone


def bars_from(closes: list[float], volume: float = 1_000_000) -> list[DailyBar]:
    return [DailyBar(close=c, high=c * 1.005, low=c * 0.995, volume=volume) for c in closes]


def rising(n: int, start: float = 100.0, step: float = 0.5) -> list[float]:
    return [start + i * step for i in range(n)]


def test_every_label_comes_with_reasons() -> None:
    result = engine.evaluate(bars_from(rising(260)), headlines=None)
    assert result.label is Label.BULLISH
    assert result.reasons, "a label without reasons is a bug"
    assert any("above 200-day average" in r for r in result.reasons)
    assert any("52-week high" in r for r in result.reasons)
    assert any("overbought" in r for r in result.reasons)  # strong trends are flagged overbought too
    assert -100 <= result.score <= 100


def test_downtrend_is_bearish() -> None:
    result = engine.evaluate(bars_from(rising(260, start=300, step=-0.5)), headlines=None)
    assert result.label is Label.BEARISH
    assert any("below 200-day average" in r for r in result.reasons)
    assert any("52-week low" in r for r in result.reasons)


def test_short_history_skips_rules_instead_of_inventing_values() -> None:
    result = engine.evaluate(bars_from(rising(30)), headlines=None)
    skipped = {s.rule: s.reason for s in result.skipped}
    assert "sma200" in skipped and "needs 200 days of prices (have 30)" in skipped["sma200"]
    assert "macd" in skipped and "52w" in skipped
    assert result.indicators["sma200"] is None
    assert [s.rule for s in result.signals] == ["rsi"]


def test_no_data_is_neutral_and_says_why() -> None:
    result = engine.evaluate([], headlines=[])
    assert result.label is Label.NEUTRAL and result.score == 0
    assert any(s.rule == "all" for s in result.skipped)
    assert result.close is None


def test_flat_prices_are_neutral_without_errors() -> None:
    result = engine.evaluate(bars_from([50.0] * 260), headlines=None)
    rsi = next(s for s in result.signals if s.rule == "rsi")
    assert rsi.direction == 0 and "RSI 50" in rsi.reason


def test_volume_spike_direction_follows_the_day() -> None:
    bars = bars_from(rising(40))
    bars[-1] = DailyBar(close=bars[-1].close, high=bars[-1].high, low=bars[-1].low, volume=5_000_000)
    signal = engine.volume_rule(bars)
    assert isinstance(signal, Signal) and signal.direction == 1
    assert "5.0× its 20-day average on an up day" in signal.reason  # noqa: RUF001
    assert engine.volume_rule(bars_from(rising(40))) is None  # no spike, no signal


def test_missing_volume_is_skipped() -> None:
    bars = [DailyBar(close=c, high=c, low=c, volume=None) for c in rising(40)]
    assert isinstance(engine.volume_rule(bars), Skipped)


def test_macd_crossover_is_reported_with_timing() -> None:
    closes = [100.0] * 40 + [100.0 + i * 2 for i in range(1, 4)]  # flat, then a sharp turn up
    signal = engine.macd_rule(closes)
    assert isinstance(signal, Signal)
    assert signal.direction == 1 and "Bullish MACD crossover" in signal.reason


def test_golden_cross_is_reported_on_the_cross_and_expires() -> None:
    closes = rising(260, start=300, step=-0.5) + rising(80, start=170, step=3.0)
    sma50, sma200 = ind.sma(closes, 50), ind.sma(closes, 200)
    cross = next(
        i
        for i in range(201, len(closes))
        if (a := sma50[i]) is not None
        and (b := sma200[i]) is not None
        and (pa := sma50[i - 1]) is not None
        and (pb := sma200[i - 1]) is not None
        and pa - pb <= 0 < a - b
    )

    def ma_cross(upto: int) -> list[Signal]:
        rules = engine.trend_rules(closes[: upto + 1])
        return [r for r in rules if isinstance(r, Signal) and r.rule == "ma_cross"]

    (on_the_day,) = ma_cross(cross)
    assert on_the_day.direction == 1 and on_the_day.reason.endswith("200-day today")
    (three_later,) = ma_cross(cross + 3)
    assert three_later.reason.endswith("3 sessions ago")
    assert ma_cross(cross + 6) == []  # beyond the 5-session lookback: no longer a signal
    assert ma_cross(cross - 1) == []


def test_news_rule() -> None:
    positive = ["Apple beats estimates", "Stock surges to record", "Analysts upgrade Apple", "Quiet day"]
    signal = engine.news_rule(positive)
    assert (
        isinstance(signal, Signal)
        and signal.direction == 1
        and "3 positive, 0 negative of 4" in signal.reason
    )
    assert isinstance(engine.news_rule(["one", "two"]), Skipped)
    assert isinstance(engine.news_rule(None), Skipped)
    assert news_tone(["Shares plunge after miss", "Profit jumps"]).score == 0.0


def test_score_thresholds() -> None:
    def sig(direction: int, weight: float = 1.0) -> Signal:
        return Signal("x", direction, weight, "r")

    assert engine.score_signals([sig(1), sig(0), sig(0)]) == (33, Label.BULLISH)
    assert engine.score_signals([sig(-1), sig(0), sig(0)]) == (-33, Label.BEARISH)
    assert engine.score_signals([sig(1), sig(0), sig(0), sig(0)]) == (25, Label.NEUTRAL)
    assert engine.score_signals([]) == (0, Label.NEUTRAL)
    assert engine.score_signals([sig(1, 1.5), sig(-1, 0.5)]) == (50, Label.BULLISH)

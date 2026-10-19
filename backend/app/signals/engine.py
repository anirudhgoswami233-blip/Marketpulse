"""Signal rules and scoring. Pure functions over daily bars and headlines; no I/O.

Each rule returns a Signal (direction -1/0/+1, weight, plain-English reason), or a skip with the reason
(usually not enough history). Rules that only fire on an event (a crossover, a volume spike, being near the
52-week range) return nothing when the event didn't happen, so they don't dilute the score.

Score = sum(direction * weight) / sum(weight) over evaluated rules, scaled to -100..+100.
Labels: >= +30 "Bullish signals", <= -30 "Bearish signals", otherwise "Neutral".
These are descriptions of indicator readings, never instructions to buy or sell.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from app.signals import indicators as ind
from app.signals.sentiment import news_tone

ENGINE_VERSION = "v1"
DISCLAIMER = "Educational information based on technical indicators, not financial advice."

BULLISH_THRESHOLD = 30
BEARISH_THRESHOLD = -30
RSI_OVERSOLD, RSI_OVERBOUGHT = 30.0, 70.0
MACD_CROSS_LOOKBACK = 3  # sessions
MA_CROSS_LOOKBACK = 5  # sessions
VOLUME_SPIKE_MULTIPLE = 2.0
VOLUME_LOOKBACK = 20
WEEK52_SESSIONS = 252
WEEK52_PROXIMITY = 0.03
MIN_HEADLINES = 3
TONE_THRESHOLD = 0.2


class Label(StrEnum):
    BULLISH = "Bullish signals"
    NEUTRAL = "Neutral"
    BEARISH = "Bearish signals"


@dataclass(frozen=True)
class DailyBar:
    close: float
    high: float
    low: float
    volume: float | None


@dataclass(frozen=True)
class Signal:
    rule: str
    direction: int
    weight: float
    reason: str


@dataclass(frozen=True)
class Skipped:
    rule: str
    reason: str


@dataclass(frozen=True)
class SignalResult:
    score: int
    label: Label
    signals: list[Signal]
    skipped: list[Skipped]
    close: float | None
    indicators: dict[str, float | None] = field(default_factory=dict)

    @property
    def reasons(self) -> list[str]:
        return [s.reason for s in self.signals]


def _fmt(value: float) -> str:
    return f"{value:,.2f}"


def rsi_rule(closes: Sequence[float]) -> Signal | Skipped:
    value = ind.rsi(closes)[-1] if closes else None
    if value is None:
        return Skipped("rsi", f"RSI needs 15 days of prices (have {len(closes)}).")
    if value < RSI_OVERSOLD:
        return Signal("rsi", 1, 1.0, f"RSI {value:.0f} = oversold (below {RSI_OVERSOLD:.0f})")
    if value > RSI_OVERBOUGHT:
        return Signal("rsi", -1, 1.0, f"RSI {value:.0f} = overbought (above {RSI_OVERBOUGHT:.0f})")
    return Signal("rsi", 0, 1.0, f"RSI {value:.0f} = neutral range")


def macd_rule(closes: Sequence[float]) -> Signal | Skipped:
    result = ind.macd(closes)
    if not closes or result.histogram[-1] is None:
        return Skipped("macd", f"MACD needs 34 days of prices (have {len(closes)}).")
    cross = ind.bars_since_sign_change(result.histogram, MACD_CROSS_LOOKBACK)
    if cross is not None:
        bars_ago, sign = cross
        when = "today" if bars_ago == 0 else f"{bars_ago} session{'s' if bars_ago > 1 else ''} ago"
        side = "above" if sign > 0 else "below"
        kind = "Bullish" if sign > 0 else "Bearish"
        return Signal("macd", sign, 1.0, f"{kind} MACD crossover: MACD crossed {side} its signal line {when}")
    hist = result.histogram[-1]
    position = "above" if hist is not None and hist > 0 else "below"
    return Signal("macd", 0, 1.0, f"No recent MACD crossover (MACD {position} signal line)")


def trend_rules(closes: Sequence[float]) -> list[Signal | Skipped]:
    out: list[Signal | Skipped] = []
    close = closes[-1] if closes else None
    sma50, sma200 = ind.sma(closes, 50), ind.sma(closes, 200)
    for n, series, weight in ((200, sma200, 1.5), (50, sma50, 1.0)):
        value = series[-1] if series else None
        if value is None or close is None:
            out.append(Skipped(f"sma{n}", f"{n}-day average needs {n} days of prices (have {len(closes)})."))
            continue
        above = close > value
        out.append(
            Signal(
                f"sma{n}",
                1 if above else -1,
                weight,
                f"Price {_fmt(close)} {'above' if above else 'below'} {n}-day average ({_fmt(value)})",
            )
        )
    if sma200 and sma200[-1] is not None:
        spread: ind.Series = [
            a - b if a is not None and b is not None else None for a, b in zip(sma50, sma200, strict=True)
        ]
        cross = ind.bars_since_sign_change(spread, MA_CROSS_LOOKBACK)
        if cross is not None:
            bars_ago, sign = cross
            name = "Golden cross" if sign > 0 else "Death cross"
            side = "above" if sign > 0 else "below"
            when = "today" if bars_ago == 0 else f"{bars_ago} session{'s' if bars_ago > 1 else ''} ago"
            out.append(Signal("ma_cross", sign, 1.0, f"{name}: 50-day average crossed {side} 200-day {when}"))
    return out


def volume_rule(bars: Sequence[DailyBar]) -> Signal | Skipped | None:
    if len(bars) < VOLUME_LOOKBACK + 2:
        return Skipped("volume", f"Volume check needs {VOLUME_LOOKBACK + 2} days (have {len(bars)}).")
    today, previous = bars[-1], bars[-2]
    history = [b.volume for b in bars[-VOLUME_LOOKBACK - 1 : -1] if b.volume is not None]
    avg = ind.average(history)
    if today.volume is None or avg is None or len(history) < VOLUME_LOOKBACK or avg <= 0:
        return Skipped("volume", "Volume data isn't available for this symbol.")
    multiple = today.volume / avg
    if multiple <= VOLUME_SPIKE_MULTIPLE:
        return None
    if today.close > previous.close:
        return Signal("volume", 1, 0.5, f"Volume {multiple:.1f}× its 20-day average on an up day")  # noqa: RUF001 - multiplication sign is intended
    if today.close < previous.close:
        return Signal("volume", -1, 0.5, f"Volume {multiple:.1f}× its 20-day average on a down day")  # noqa: RUF001 - multiplication sign is intended
    return Signal("volume", 0, 0.5, f"Volume {multiple:.1f}× its 20-day average with an unchanged close")  # noqa: RUF001 - multiplication sign is intended


def week52_rule(bars: Sequence[DailyBar]) -> Signal | Skipped | None:
    if len(bars) < WEEK52_SESSIONS:
        return Skipped("52w", f"52-week range needs {WEEK52_SESSIONS} days of prices (have {len(bars)}).")
    window = bars[-WEEK52_SESSIONS:]
    high, low, close = max(b.high for b in window), min(b.low for b in window), bars[-1].close
    from_high = (high - close) / high if high else 1.0
    from_low = (close - low) / low if low else 1.0
    if from_high <= WEEK52_PROXIMITY:
        return Signal("52w", 1, 0.75, f"Within {from_high:.1%} of its 52-week high ({_fmt(high)})")
    if from_low <= WEEK52_PROXIMITY:
        return Signal("52w", -1, 0.75, f"Within {from_low:.1%} of its 52-week low ({_fmt(low)})")
    return None


def news_rule(headlines: Sequence[str] | None, skip_reason: str | None = None) -> Signal | Skipped:
    if headlines is None:
        return Skipped("news", skip_reason or "News wasn't available for this symbol.")
    if len(headlines) < MIN_HEADLINES:
        return Skipped("news", f"Too few recent headlines to judge tone ({len(headlines)}).")
    tone = news_tone(headlines)
    summary = f"{tone.positive} positive, {tone.negative} negative of {tone.headlines} headlines"
    if tone.score >= TONE_THRESHOLD:
        return Signal("news", 1, 0.75, f"News tone positive ({summary})")
    if tone.score <= -TONE_THRESHOLD:
        return Signal("news", -1, 0.75, f"News tone negative ({summary})")
    return Signal("news", 0, 0.75, f"News tone mixed ({summary})")


def score_signals(signals: Sequence[Signal]) -> tuple[int, Label]:
    total_weight = sum(s.weight for s in signals)
    if total_weight == 0:
        return 0, Label.NEUTRAL
    score = round(sum(s.direction * s.weight for s in signals) / total_weight * 100)
    if score >= BULLISH_THRESHOLD:
        return score, Label.BULLISH
    if score <= BEARISH_THRESHOLD:
        return score, Label.BEARISH
    return score, Label.NEUTRAL


def evaluate(
    bars: Sequence[DailyBar], headlines: Sequence[str] | None, news_skip_reason: str | None = None
) -> SignalResult:
    """Run every rule over oldest-first daily bars and recent headlines."""
    closes = [b.close for b in bars]
    outcomes: list[Signal | Skipped | None] = [
        rsi_rule(closes),
        macd_rule(closes),
        *trend_rules(closes),
        volume_rule(bars),
        week52_rule(bars),
        news_rule(headlines, news_skip_reason),
    ]
    signals = [o for o in outcomes if isinstance(o, Signal)]
    skipped = [o for o in outcomes if isinstance(o, Skipped)]
    if not signals:
        skipped.append(Skipped("all", "Not enough price history to compute any signal yet."))
    score, label = score_signals(signals)
    rsi_last = ind.rsi(closes)[-1] if closes else None
    sma50 = ind.sma(closes, 50)[-1] if closes else None
    sma200 = ind.sma(closes, 200)[-1] if closes else None
    return SignalResult(
        score=score,
        label=label,
        signals=signals,
        skipped=skipped,
        close=closes[-1] if closes else None,
        indicators={"rsi14": rsi_last, "sma50": sma50, "sma200": sma200},
    )

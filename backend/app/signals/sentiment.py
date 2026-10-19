"""Keyword tone score for news headlines. Finnhub's /news-sentiment is premium, so this is deliberately
simple and transparent: count positive and negative keywords. Pure function, no I/O."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

POSITIVE = frozenset(
    {
        "beat",
        "beats",
        "surge",
        "surges",
        "soar",
        "soars",
        "jump",
        "jumps",
        "rally",
        "rallies",
        "gain",
        "gains",
        "record",
        "upgrade",
        "upgraded",
        "outperform",
        "bullish",
        "strong",
        "growth",
        "profit",
        "raises",
        "raised",
        "boost",
        "boosts",
        "approval",
        "approved",
        "wins",
        "win",
        "rebound",
        "tops",
    }
)
NEGATIVE = frozenset(
    {
        "miss",
        "misses",
        "plunge",
        "plunges",
        "slump",
        "slumps",
        "fall",
        "falls",
        "drop",
        "drops",
        "tumble",
        "tumbles",
        "downgrade",
        "downgraded",
        "underperform",
        "bearish",
        "weak",
        "loss",
        "losses",
        "cut",
        "cuts",
        "lawsuit",
        "probe",
        "recall",
        "warning",
        "warns",
        "layoffs",
        "fraud",
        "bankruptcy",
        "sinks",
    }
)
_WORD = re.compile(r"[a-z]+")


@dataclass(frozen=True)
class Tone:
    score: float  # -1 (all negative) .. +1 (all positive)
    positive: int  # headlines leaning positive
    negative: int  # headlines leaning negative
    headlines: int


def headline_tone(headline: str) -> int:
    words = _WORD.findall(headline.lower())
    pos = sum(1 for w in words if w in POSITIVE)
    neg = sum(1 for w in words if w in NEGATIVE)
    return (pos > neg) - (neg > pos)


def news_tone(headlines: Sequence[str]) -> Tone:
    tones = [headline_tone(h) for h in headlines]
    positive = tones.count(1)
    negative = tones.count(-1)
    score = (positive - negative) / len(tones) if tones else 0.0
    return Tone(score=score, positive=positive, negative=negative, headlines=len(tones))

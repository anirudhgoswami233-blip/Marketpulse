"""Classifies a news headline into an event category and a materiality level. Pure, no I/O.

Descriptive only: a category names *what kind of event* a headline reports; it never implies a trade.
Finnhub's /news-sentiment is premium, so this — like sentiment.py — is deliberately simple and transparent
(keyword/pattern matching) and reports which keywords fired, so a label is always explainable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from app.signals.sentiment import headline_tone


class NewsCategory(StrEnum):
    EARNINGS = "earnings"
    GUIDANCE = "guidance"
    MA = "m&a"
    RATING_CHANGE = "rating_change"
    LEGAL_REG = "legal_reg"
    PRODUCT = "product"
    MACRO = "macro"
    OTHER = "other"


class Materiality(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


CATEGORY_LABELS: dict[NewsCategory, str] = {
    NewsCategory.EARNINGS: "Earnings",
    NewsCategory.GUIDANCE: "Guidance",
    NewsCategory.MA: "M&A",
    NewsCategory.RATING_CHANGE: "Analyst rating",
    NewsCategory.LEGAL_REG: "Legal / regulatory",
    NewsCategory.PRODUCT: "Product / business",
    NewsCategory.MACRO: "Macro",
    NewsCategory.OTHER: "General",
}

# Checked in priority order; the first category with a keyword hit wins. Order matters: a headline that
# mentions both earnings and a target ("beats estimates, analysts raise price target") reads as earnings.
_PATTERNS: tuple[tuple[NewsCategory, tuple[str, ...]], ...] = (
    (
        NewsCategory.EARNINGS,
        (
            "earnings",
            "eps",
            "revenue",
            "quarterly results",
            "quarterly profit",
            "net income",
            "beats estimates",
            "misses estimates",
            "tops estimates",
            "q1",
            "q2",
            "q3",
            "q4",
        ),
    ),
    (
        NewsCategory.GUIDANCE,
        (
            "guidance",
            "forecast",
            "outlook",
            "raises full-year",
            "cuts full-year",
            "lowers outlook",
            "raises outlook",
            "profit warning",
            "full-year",
        ),
    ),
    (
        NewsCategory.MA,
        (
            "acquire",
            "acquires",
            "acquisition",
            "merger",
            "merges",
            "buyout",
            "takeover",
            "to buy",
            "stake",
            "spin off",
            "spinoff",
            "divest",
        ),
    ),
    (
        NewsCategory.RATING_CHANGE,
        (
            "upgrade",
            "upgrades",
            "downgrade",
            "downgrades",
            "price target",
            "initiates coverage",
            "reiterates",
            "overweight",
            "underweight",
            "outperform",
            "underperform",
            "buy rating",
            "sell rating",
        ),
    ),
    (
        NewsCategory.LEGAL_REG,
        (
            "lawsuit",
            "sues",
            "sued",
            "settlement",
            "sec",
            "ftc",
            "doj",
            "antitrust",
            "probe",
            "investigation",
            "recall",
            "subpoena",
            "fine",
            "penalty",
            "regulator",
            "regulatory",
            "fraud",
        ),
    ),
    (
        NewsCategory.PRODUCT,
        (
            "launch",
            "launches",
            "unveils",
            "partnership",
            "contract",
            "approval",
            "approved",
            "fda",
            "patent",
            "rollout",
            "expands",
        ),
    ),
    (
        NewsCategory.MACRO,
        (
            "fed",
            "federal reserve",
            "inflation",
            "interest rate",
            "rate cut",
            "rate hike",
            "jobs report",
            "gdp",
            "tariff",
            "recession",
            "cpi",
        ),
    ),
)

_BASE_MATERIALITY: dict[NewsCategory, Materiality] = {
    NewsCategory.EARNINGS: Materiality.HIGH,
    NewsCategory.GUIDANCE: Materiality.HIGH,
    NewsCategory.MA: Materiality.HIGH,
    NewsCategory.RATING_CHANGE: Materiality.MEDIUM,
    NewsCategory.LEGAL_REG: Materiality.MEDIUM,
    NewsCategory.PRODUCT: Materiality.LOW,
    NewsCategory.MACRO: Materiality.LOW,
    NewsCategory.OTHER: Materiality.LOW,
}

# A confirmed next-session move of at least this magnitude (%) bumps materiality up one level: the market
# treated the headline as material, whatever the keywords said.
MOVE_THRESHOLD = 5

_RULES: tuple[tuple[NewsCategory, tuple[tuple[str, re.Pattern[str]], ...]], ...] = tuple(
    (cat, tuple((kw, re.compile(r"\b" + re.escape(kw) + r"\b")) for kw in kws)) for cat, kws in _PATTERNS
)
_ORDER = (Materiality.LOW, Materiality.MEDIUM, Materiality.HIGH)


@dataclass(frozen=True)
class NewsImpact:
    category: NewsCategory
    materiality: Materiality
    tone: int  # -1 negative, 0 neutral, +1 positive (from sentiment.headline_tone)
    matched: tuple[str, ...]  # keywords that fired — keeps the label explainable and testable


def _bump(level: Materiality) -> Materiality:
    return _ORDER[min(_ORDER.index(level) + 1, len(_ORDER) - 1)]


def bumped_materiality(base: Materiality, price_change_pct: Decimal | None) -> Materiality:
    """Raise materiality one level when the stock's confirmed move says the market treated it as material.
    Shared by the keyword classifier and the LLM-enriched path so both react the same way."""
    if price_change_pct is not None and abs(price_change_pct) >= MOVE_THRESHOLD:
        return _bump(base)
    return base


def classify(headline: str, summary: str = "", *, price_change_pct: Decimal | None = None) -> NewsImpact:
    text = f"{headline} {summary}".lower()
    category = NewsCategory.OTHER
    matched: tuple[str, ...] = ()
    for cat, rules in _RULES:
        hits = tuple(kw for kw, rx in rules if rx.search(text))
        if hits:
            category, matched = cat, hits
            break
    materiality = bumped_materiality(_BASE_MATERIALITY[category], price_change_pct)
    return NewsImpact(
        category=category, materiality=materiality, tone=headline_tone(headline), matched=matched
    )

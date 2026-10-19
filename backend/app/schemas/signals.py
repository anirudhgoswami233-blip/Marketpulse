from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel

from app.signals.engine import DISCLAIMER


class SignalReason(BaseModel):
    rule: str
    direction: int
    weight: float
    reason: str


class SkippedRule(BaseModel):
    rule: str
    reason: str


class OutcomeOut(BaseModel):
    horizon_days: int
    outcome_date: date
    return_pct: Decimal


class SignalOut(BaseModel):
    id: int
    symbol: str
    display_symbol: str
    description: str
    signal_date: date
    engine_version: str
    score: int
    label: str
    reasons: list[SignalReason]
    skipped: list[SkippedRule]
    indicators: dict[str, Any]
    price_at_signal: Decimal | None
    currency: str | None
    outcomes: list[OutcomeOut] = []
    disclaimer: str = DISCLAIMER


class LabelStatsOut(BaseModel):
    label: str
    horizon_days: int
    count: int
    avg_return_pct: Decimal | None
    hit_rate_pct: Decimal | None
    enough_data: bool


class PerformanceOut(BaseModel):
    stats: list[LabelStatsOut]
    total_signals: int
    min_sample: int
    disclaimer: str = DISCLAIMER


class BriefItemOut(BaseModel):
    source: str
    signal: SignalOut


class BriefOut(BaseModel):
    id: int
    brief_date: date
    generated_at: datetime
    generator: str
    summary_md: str
    overnight: dict[str, Any]
    items: list[BriefItemOut]
    emailed_at: datetime | None
    disclaimer: str = DISCLAIMER


class BriefStatus(BaseModel):
    brief: BriefOut | None
    generating: bool
    # When today's scheduled brief is due, in UTC; None on weekends (briefs run on weekdays).
    next_scheduled_at: datetime | None
    email_available: bool


class BriefSummaryOut(BaseModel):
    brief_date: date
    generated_at: datetime
    signal_count: int

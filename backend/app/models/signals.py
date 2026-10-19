from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class SignalRecord(Base):
    """One evaluation of the signal engine for a symbol on a trading day. Shared by every user's brief."""

    __tablename__ = "signals"
    __table_args__ = (UniqueConstraint("symbol_id", "signal_date", "engine_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol_id: Mapped[int] = mapped_column(ForeignKey("symbols.id", ondelete="CASCADE"), index=True)
    # The last completed trading session the signal is based on (exchange-local date).
    signal_date: Mapped[date] = mapped_column(Date, index=True)
    engine_version: Mapped[str] = mapped_column(String(16))
    score: Mapped[int] = mapped_column(Integer)
    label: Mapped[str] = mapped_column(String(32))
    # [{"rule", "direction", "weight", "reason"}], always non-empty unless everything was skipped.
    reasons: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    skipped: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    indicators: Mapped[dict[str, Any]] = mapped_column(JSON)
    price_at_signal: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    currency: Mapped[str | None] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class SignalOutcome(Base):
    """How the price moved N trading days after a signal; feeds the Signal History page."""

    __tablename__ = "signal_outcomes"

    signal_id: Mapped[int] = mapped_column(ForeignKey("signals.id", ondelete="CASCADE"), primary_key=True)
    horizon_days: Mapped[int] = mapped_column(Integer, primary_key=True)
    outcome_date: Mapped[date] = mapped_column(Date)
    price_after: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    return_pct: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Brief(Base):
    __tablename__ = "briefs"
    __table_args__ = (UniqueConstraint("user_id", "brief_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # The user's local calendar date the brief is for.
    brief_date: Mapped[date] = mapped_column(Date)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    generator: Mapped[str] = mapped_column(String(16))  # "template" | "llm"
    summary_md: Mapped[str] = mapped_column(Text)
    overnight: Mapped[dict[str, Any]] = mapped_column(JSON)
    emailed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BriefSignal(Base):
    __tablename__ = "brief_signals"

    brief_id: Mapped[int] = mapped_column(ForeignKey("briefs.id", ondelete="CASCADE"), primary_key=True)
    signal_id: Mapped[int] = mapped_column(ForeignKey("signals.id", ondelete="CASCADE"), primary_key=True)
    source: Mapped[str] = mapped_column(String(16))  # "watchlist" | "trending"

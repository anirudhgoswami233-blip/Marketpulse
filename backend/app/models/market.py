from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

PRICE = Numeric(20, 6)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Exchange(Base):
    __tablename__ = "exchanges"

    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    mic: Mapped[str | None] = mapped_column(String(8))
    timezone: Mapped[str] = mapped_column(String(64))
    currency: Mapped[str | None] = mapped_column(String(8))
    country: Mapped[str | None] = mapped_column(String(64))
    region: Mapped[str] = mapped_column(String(32))


class Symbol(Base):
    __tablename__ = "symbols"
    __table_args__ = (UniqueConstraint("symbol", "exchange_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(64), index=True)
    exchange_code: Mapped[str] = mapped_column(ForeignKey("exchanges.code"))
    display_symbol: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(String(256))
    type: Mapped[str] = mapped_column(String(64))
    currency: Mapped[str | None] = mapped_column(String(8))
    mic: Mapped[str | None] = mapped_column(String(8))
    figi: Mapped[str | None] = mapped_column(String(16))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


# Case-insensitive prefix/contains search on company names.
Index("ix_symbols_description_lower", func.lower(Symbol.description))


class PriceBar(Base):
    """Daily OHLCV history. Filled from the history provider once, then topped up daily."""

    __tablename__ = "price_bars"

    symbol_id: Mapped[int] = mapped_column(ForeignKey("symbols.id", ondelete="CASCADE"), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    open: Mapped[Decimal] = mapped_column(PRICE)
    high: Mapped[Decimal] = mapped_column(PRICE)
    low: Mapped[Decimal] = mapped_column(PRICE)
    close: Mapped[Decimal] = mapped_column(PRICE)
    volume: Mapped[int | None] = mapped_column(BigInteger)
    source: Mapped[str] = mapped_column(String(32))

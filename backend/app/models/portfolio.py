from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

MONEY = Numeric(20, 6)
QUANTITY = Numeric(20, 6)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Watchlist(Base):
    __tablename__ = "watchlists"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(60))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"
    __table_args__ = (UniqueConstraint("watchlist_id", "symbol_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    watchlist_id: Mapped[int] = mapped_column(ForeignKey("watchlists.id", ondelete="CASCADE"), index=True)
    symbol_id: Mapped[int] = mapped_column(ForeignKey("symbols.id", ondelete="CASCADE"))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Portfolio(Base):
    """A paper-trading account. `version` guards against concurrent orders overspending cash."""

    __tablename__ = "portfolios"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(60))
    base_currency: Mapped[str] = mapped_column(String(8))
    starting_cash: Mapped[Decimal] = mapped_column(MONEY)
    cash: Mapped[Decimal] = mapped_column(MONEY)
    version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Position(Base):
    """Current holding per symbol, derived from trades and updated in the same transaction."""

    __tablename__ = "positions"

    portfolio_id: Mapped[int] = mapped_column(
        ForeignKey("portfolios.id", ondelete="CASCADE"), primary_key=True
    )
    symbol_id: Mapped[int] = mapped_column(ForeignKey("symbols.id"), primary_key=True)
    quantity: Mapped[Decimal] = mapped_column(QUANTITY)
    avg_cost: Mapped[Decimal] = mapped_column(MONEY)
    currency: Mapped[str] = mapped_column(String(8))


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id", ondelete="CASCADE"), index=True)
    symbol_id: Mapped[int] = mapped_column(ForeignKey("symbols.id"))
    side: Mapped[str] = mapped_column(String(4))  # "buy" | "sell"
    quantity: Mapped[Decimal] = mapped_column(QUANTITY)
    price: Mapped[Decimal] = mapped_column(MONEY)
    currency: Mapped[str] = mapped_column(String(8))
    fx_rate_to_base: Mapped[Decimal] = mapped_column(Numeric(20, 10), default=Decimal(1))
    fee: Mapped[Decimal] = mapped_column(MONEY, default=Decimal(0))
    # Profit or loss locked in by a sell versus the average cost; null for buys.
    realized_pnl: Mapped[Decimal | None] = mapped_column(MONEY)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    price_source: Mapped[str] = mapped_column(String(32))
    price_as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))

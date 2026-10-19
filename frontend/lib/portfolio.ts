import type { LiveTrade, Portfolio, Position } from "@/types/api";

// Display-only re-valuation with live prices. The server's Decimal figures stay authoritative; these
// numbers just keep the page moving between refreshes.

export interface LivePosition {
  position: Position;
  price: number | null;
  marketValue: number | null;
  unrealizedPnl: number | null;
  unrealizedPnlPct: number | null;
  live: boolean;
}

export function revaluePosition(position: Position, trade: LiveTrade | undefined): LivePosition {
  const quantity = Number(position.quantity);
  const costBasis = Number(position.cost_basis);
  const livePrice = trade && (!position.price_as_of || trade.timestamp > position.price_as_of) ? Number(trade.price) : null;
  const price = livePrice ?? (position.last_price !== null ? Number(position.last_price) : null);
  if (price === null || !Number.isFinite(price)) {
    return { position, price: null, marketValue: null, unrealizedPnl: null, unrealizedPnlPct: null, live: false };
  }
  const marketValue = quantity * price;
  const pnl = marketValue - costBasis;
  return {
    position,
    price,
    marketValue,
    unrealizedPnl: pnl,
    unrealizedPnlPct: costBasis ? (pnl / costBasis) * 100 : null,
    live: livePrice !== null,
  };
}

export interface LiveTotals {
  equity: number;
  marketValue: number;
  totalReturn: number;
  totalReturnPct: number | null;
}

/** Totals with live prices; positions without any price count at cost, matching the server. */
export function liveTotals(portfolio: Portfolio, positions: LivePosition[]): LiveTotals {
  const marketValue = positions.reduce((sum, p) => sum + (p.marketValue ?? Number(p.position.cost_basis)), 0);
  const equity = Number(portfolio.cash) + marketValue;
  const starting = Number(portfolio.starting_cash);
  const totalReturn = equity - starting;
  return { equity, marketValue, totalReturn, totalReturnPct: starting ? (totalReturn / starting) * 100 : null };
}

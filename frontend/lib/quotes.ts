import type { LiveTrade, Quote } from "@/types/api";

export interface DisplayQuote {
  price: string;
  change: string | null;
  changePct: string | null;
  timestamp: string | null;
  live: boolean;
}

/** Overlay a newer live trade on a REST quote, recomputing change against the previous close. */
export function mergeLiveTrade(quote: Quote | null, trade: LiveTrade | undefined): DisplayQuote | null {
  if (!quote && !trade) return null;
  const base: DisplayQuote | null = quote
    ? { price: quote.price, change: quote.change, changePct: quote.change_pct, timestamp: quote.timestamp, live: false }
    : null;
  if (!trade) return base;

  const tradeTime = new Date(trade.timestamp).getTime();
  const quoteTime = quote?.timestamp ? new Date(quote.timestamp).getTime() : 0;
  if (base && tradeTime <= quoteTime) return base;

  const prevClose = quote?.prev_close ? Number(quote.prev_close) : null;
  const price = Number(trade.price);
  if (prevClose && Number.isFinite(price)) {
    const change = price - prevClose;
    return {
      price: trade.price,
      change: change.toFixed(4),
      changePct: ((change / prevClose) * 100).toFixed(4),
      timestamp: trade.timestamp,
      live: true,
    };
  }
  return { price: trade.price, change: null, changePct: null, timestamp: trade.timestamp, live: true };
}

// Server-only cached wrappers around the public, non-user API endpoints. Each is a Cache Components
// `"use cache"` function with an explicit `cacheLife`, so on Vercel its output is stored and reused across
// requests: visitors get the data from cache instead of waiting for the Render backend. The cached value is
// the backend's full envelope, including its `as_of` timestamp, so "data as of …" labels stay accurate —
// they describe when the cached data was captured, which is exactly what the label means.
//
// Only import this from Server Components. Never cache user-specific data (watchlists, portfolio, auth) or
// live prices (quotes, the SSE stream): those stay uncached so they're always fresh and per-user.
//
// These functions throw on backend errors (an uncaught throw is never cached), so callers keep their own
// try/catch and error UI. Keeping the data dynamic at the component level (via `connection()` on the
// non-param pages, or being downstream of `await params`) means the cache fills at request time, not at
// build — `next build` never has to reach the backend.

import { cacheLife } from "next/cache";

import { api } from "@/lib/api";
import type {
  ChartRange,
  CompanyProfile,
  Envelope,
  ForexBoard,
  KeyMetrics,
  MacroDashboard,
  MarketOverview,
  NewsItem,
  Signal,
  SignalLabel,
  SignalPerformance,
  SymbolInfo,
} from "@/types/api";

// 5-minute profile for feeds that move through the day (news, forex rates).
const FIVE_MIN = { stale: 300, revalidate: 300, expire: 3600 } as const;

/** Markets overview snapshot (regional ETF proxies, movers, sectors). Live prices overlay via SSE, uncached. */
export async function cachedOverview(): Promise<MarketOverview> {
  "use cache";
  cacheLife("minutes");
  return api.overview();
}

/** Macro dashboard (FRED series). Each series is published at most daily. */
export async function cachedMacro(): Promise<MacroDashboard> {
  "use cache";
  cacheLife("hours");
  return api.macro();
}

/** Symbol directory entry (exchange, flags). Seeded once into the DB; changes rarely. */
export async function cachedStockInfo(symbol: string): Promise<SymbolInfo> {
  "use cache";
  cacheLife("days");
  return api.stock(symbol);
}

/** Company profile (market cap, sector, logo). Backend caches it 24h. */
export async function cachedProfile(symbol: string): Promise<Envelope<CompanyProfile>> {
  "use cache";
  cacheLife("hours");
  return api.profile(symbol);
}

/** Key statistics (P/E, EPS, 52-week range). Fundamentals, not the live quote. */
export async function cachedMetrics(symbol: string): Promise<Envelope<KeyMetrics>> {
  "use cache";
  cacheLife("hours");
  return api.metrics(symbol);
}

/** Company news headlines. */
export async function cachedNews(symbol: string): Promise<Envelope<NewsItem[]>> {
  "use cache";
  cacheLife(FIVE_MIN);
  return api.news(symbol);
}

/** Technical signal for the last completed session. Stable for the trading day. */
export async function cachedSignal(symbol: string): Promise<Signal> {
  "use cache";
  cacheLife("hours");
  return api.signal(symbol);
}

/** Price history for a range. Used to seed the chart's default range; longer ranges fetch on demand. */
export async function cachedChart(symbol: string, range: ChartRange) {
  "use cache";
  cacheLife("hours");
  return api.chart(symbol, range);
}

/** Forex & metals board (public; rates are indicative and delayed). */
export async function cachedForex(): Promise<ForexBoard> {
  "use cache";
  cacheLife(FIVE_MIN);
  return api.forex();
}

/** Aggregate signal-label performance. */
export async function cachedSignalPerformance(): Promise<SignalPerformance> {
  "use cache";
  cacheLife("minutes");
  return api.signalPerformance();
}

/** Recent stored signals, optionally filtered by label. */
export async function cachedSignalHistory(label?: SignalLabel): Promise<Signal[]> {
  "use cache";
  cacheLife("minutes");
  return api.signalHistory({ label, limit: 50 });
}

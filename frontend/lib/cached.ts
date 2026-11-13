// Server-only cached wrappers around the public, non-user API endpoints. Each is a Cache Components
// `"use cache"` function with an explicit `cacheLife`, so on Vercel its output is stored and reused across
// requests: visitors get the data from cache instead of waiting for the Render backend. The cached value is
// the backend's full envelope, including its `as_of` timestamp, so "data as of …" labels stay accurate —
// they describe when the cached data was captured, which is exactly what the label means.
//
// Only import this from Server Components. Never cache user-specific data (watchlists, portfolio, auth) or
// live prices (quotes, the SSE stream): those stay uncached so they're always fresh and per-user.
//
// Errors are RETURNED, not thrown. A thrown value is redacted as it crosses the `use cache` boundary (so the
// backend's code/message would be lost and every failure would read as a generic "something went wrong"),
// whereas a returned value serializes intact. Each function catches the ApiError inside the cache scope,
// returns it as plain data with a short `cacheLife` (so a transient failure isn't cached and retries work),
// and callers rebuild it with `toSettled` outside the boundary.
//
// Keeping the data dynamic at the component level (via `connection()` on the non-param pages, or being
// downstream of `await params`) means the cache fills at request time, not at build — `next build` never
// has to reach the backend.

import { cacheLife } from "next/cache";

import { ApiError, api, toApiError } from "@/lib/api";
import type {
  Chart,
  ChartRange,
  CompanyProfile,
  EarningsSurprise,
  Envelope,
  ForexBoard,
  KeyMetrics,
  MacroDashboard,
  MarketOverview,
  NewsItem,
  Peer,
  RecommendationTrend,
  Signal,
  SignalLabel,
  SignalPerformance,
  SymbolInfo,
} from "@/types/api";

// 5-minute profile for feeds that move through the day (news, forex rates).
const FIVE_MIN = { stale: 300, revalidate: 300, expire: 3600 } as const;

/** A serializable success-or-error result. Error details survive the `use cache` boundary; a throw wouldn't. */
export type Cached<T> = { ok: true; value: T } | { ok: false; error: { message: string; status: number; code: string } };

function failed(error: unknown): Cached<never> {
  const e = toApiError(error);
  return { ok: false, error: { message: e.message, status: e.status, code: String(e.code) } };
}

/** Rebuild the `{ data, error }` shape callers use, reconstructing the ApiError outside the cache boundary. */
export function toSettled<T>(r: Cached<T>): { data: T; error: null } | { data: null; error: ApiError } {
  return r.ok
    ? { data: r.value, error: null }
    : { data: null, error: new ApiError(r.error.message, r.error.status, r.error.code) };
}

/** Markets overview snapshot (regional ETF proxies, movers, sectors). Live prices overlay via SSE, uncached. */
export async function cachedOverview(): Promise<Cached<MarketOverview>> {
  "use cache";
  try {
    const value = await api.overview();
    cacheLife("minutes");
    return { ok: true, value };
  } catch (error) {
    cacheLife("seconds");
    return failed(error);
  }
}

/** Macro dashboard (FRED series). Each series is published at most daily. */
export async function cachedMacro(): Promise<Cached<MacroDashboard>> {
  "use cache";
  try {
    const value = await api.macro();
    cacheLife("hours");
    return { ok: true, value };
  } catch (error) {
    cacheLife("seconds");
    return failed(error);
  }
}

/** Symbol directory entry (exchange, flags). Seeded once into the DB; changes rarely. */
export async function cachedStockInfo(symbol: string): Promise<Cached<SymbolInfo>> {
  "use cache";
  try {
    const value = await api.stock(symbol);
    cacheLife("days");
    return { ok: true, value };
  } catch (error) {
    cacheLife("seconds");
    return failed(error);
  }
}

/** Company profile (market cap, sector, logo). Backend caches it 24h. */
export async function cachedProfile(symbol: string): Promise<Cached<Envelope<CompanyProfile>>> {
  "use cache";
  try {
    const value = await api.profile(symbol);
    cacheLife("hours");
    return { ok: true, value };
  } catch (error) {
    cacheLife("seconds");
    return failed(error);
  }
}

/** Key statistics (P/E, EPS, 52-week range). Fundamentals, not the live quote. */
export async function cachedMetrics(symbol: string): Promise<Cached<Envelope<KeyMetrics>>> {
  "use cache";
  try {
    const value = await api.metrics(symbol);
    cacheLife("hours");
    return { ok: true, value };
  } catch (error) {
    cacheLife("seconds");
    return failed(error);
  }
}

/** Analyst rating counts by month. Updated monthly. */
export async function cachedRecommendations(symbol: string): Promise<Cached<Envelope<RecommendationTrend[]>>> {
  "use cache";
  try {
    const value = await api.recommendations(symbol);
    cacheLife("hours");
    return { ok: true, value };
  } catch (error) {
    cacheLife("seconds");
    return failed(error);
  }
}

/** Reported EPS against estimates, by quarter. Changes once a quarter. */
export async function cachedEarningsHistory(symbol: string): Promise<Cached<Envelope<EarningsSurprise[]>>> {
  "use cache";
  try {
    const value = await api.earningsHistory(symbol);
    cacheLife("hours");
    return { ok: true, value };
  } catch (error) {
    cacheLife("seconds");
    return failed(error);
  }
}

/** Same-industry companies. Rarely changes. */
export async function cachedPeers(symbol: string): Promise<Cached<Envelope<Peer[]>>> {
  "use cache";
  try {
    const value = await api.peers(symbol);
    cacheLife("days");
    return { ok: true, value };
  } catch (error) {
    cacheLife("seconds");
    return failed(error);
  }
}

/** Company news headlines. */
export async function cachedNews(symbol: string): Promise<Cached<Envelope<NewsItem[]>>> {
  "use cache";
  try {
    const value = await api.news(symbol);
    cacheLife(FIVE_MIN);
    return { ok: true, value };
  } catch (error) {
    cacheLife("seconds");
    return failed(error);
  }
}

/** Technical signal for the last completed session. Stable for the trading day. */
export async function cachedSignal(symbol: string): Promise<Cached<Signal>> {
  "use cache";
  try {
    const value = await api.signal(symbol);
    cacheLife("hours");
    return { ok: true, value };
  } catch (error) {
    cacheLife("seconds");
    return failed(error);
  }
}

/** Price history for a range. Used to seed the chart's default range; longer ranges fetch on demand. */
export async function cachedChart(symbol: string, range: ChartRange): Promise<Cached<Envelope<Chart>>> {
  "use cache";
  try {
    const value = await api.chart(symbol, range);
    cacheLife("hours");
    return { ok: true, value };
  } catch (error) {
    cacheLife("seconds");
    return failed(error);
  }
}

/** Forex & metals board (public; rates are indicative and delayed). */
export async function cachedForex(): Promise<Cached<ForexBoard>> {
  "use cache";
  try {
    const value = await api.forex();
    cacheLife(FIVE_MIN);
    return { ok: true, value };
  } catch (error) {
    cacheLife("seconds");
    return failed(error);
  }
}

/** Aggregate signal-label performance. */
export async function cachedSignalPerformance(): Promise<Cached<SignalPerformance>> {
  "use cache";
  try {
    const value = await api.signalPerformance();
    cacheLife("minutes");
    return { ok: true, value };
  } catch (error) {
    cacheLife("seconds");
    return failed(error);
  }
}

/** Recent stored signals, optionally filtered by label. */
export async function cachedSignalHistory(label?: SignalLabel): Promise<Cached<Signal[]>> {
  "use cache";
  try {
    const value = await api.signalHistory({ label, limit: 50 });
    cacheLife("minutes");
    return { ok: true, value };
  } catch (error) {
    cacheLife("seconds");
    return failed(error);
  }
}

import { describe, expect, it, vi } from "vitest";

// cached.ts calls cacheLife() from next/cache, which only runs inside a real "use cache" scope. Stub it so the
// module's pure helper (toSettled) is importable here.
vi.mock("next/cache", () => ({ cacheLife: vi.fn() }));

import { toSettled } from "@/lib/cached";
import { rangeChange, sma, toCandlePoints, toChartPoints, toPerformance, toVolumePoints, tzOffsetSeconds } from "@/lib/chart";
import { direction, formatChange, formatCompact, formatCountdown, formatMoney, formatPct, formatPrice } from "@/lib/format";
import { mergeLiveTrade } from "@/lib/quotes";
import type { Bar, Quote } from "@/types/api";

const quote: Quote = {
  symbol: "AAPL",
  price: "100",
  change: "0",
  change_pct: "0",
  open: null,
  high: null,
  low: null,
  prev_close: "100",
  timestamp: "2026-10-19T14:00:00Z",
  currency: "USD",
};

describe("format", () => {
  it("formats prices with currency and small values with 4 decimals", () => {
    expect(formatPrice("343.46", "USD")).toContain("343.46");
    expect(formatPrice("0.123456", null)).toBe("0.1235");
    expect(formatPrice(null)).toBe("—");
  });

  it("signs changes and percentages", () => {
    expect(formatChange("1.5")).toBe("+1.50");
    expect(formatChange("-0.25")).toMatch(/0\.25$/);
    expect(formatPct("2.5")).toBe("+2.50%");
    expect(formatPct("0")).toBe("0.00%");
  });

  it("compacts large numbers", () => {
    expect(formatCompact("3750000500000", "USD")).toMatch(/3\.75T/);
  });

  it("derives direction", () => {
    expect(direction("1")).toBe("up");
    expect(direction("-1")).toBe("down");
    expect(direction(null)).toBe("flat");
  });

  it("counts down to the next session change", () => {
    const now = Date.parse("2026-10-19T14:00:00Z");
    expect(formatCountdown("2026-10-19T14:45:00Z", now)).toBe("in 45m");
    expect(formatCountdown("2026-10-19T20:00:00Z", now)).toBe("in 6h 0m");
  });
});

describe("mergeLiveTrade", () => {
  it("applies a newer trade and recomputes change", () => {
    const merged = mergeLiveTrade(quote, {
      symbol: "AAPL",
      price: "102.5",
      timestamp: "2026-10-19T14:30:00Z",
      volume: null,
    });
    expect(merged).toMatchObject({ price: "102.5", live: true });
    expect(Number(merged?.changePct)).toBeCloseTo(2.5);
  });

  it("ignores an older trade", () => {
    const merged = mergeLiveTrade(quote, { symbol: "AAPL", price: "90", timestamp: "2026-10-19T13:00:00Z", volume: null });
    expect(merged).toMatchObject({ price: "100", live: false });
  });

  it("returns null with no data at all", () => {
    expect(mergeLiveTrade(null, undefined)).toBeNull();
  });
});

describe("chart helpers", () => {
  const bar = (timestamp: string, close: string): Bar => ({
    timestamp,
    open: close,
    high: close,
    low: close,
    close,
    volume: null,
  });

  it("computes timezone offsets including DST", () => {
    expect(tzOffsetSeconds(new Date("2026-07-01T12:00:00Z"), "America/New_York")).toBe(-4 * 3600);
    expect(tzOffsetSeconds(new Date("2026-12-01T12:00:00Z"), "America/New_York")).toBe(-5 * 3600);
    expect(tzOffsetSeconds(new Date("2026-12-01T12:00:00Z"), "Asia/Kolkata")).toBe(5.5 * 3600);
  });

  it("shifts intraday points to exchange-local time but not daily points", () => {
    const bars = [bar("2026-10-16T13:30:00Z", "1")];
    const utcSeconds = Date.parse("2026-10-16T13:30:00Z") / 1000;
    expect(toChartPoints(bars, "1D", "America/New_York")[0].time).toBe(utcSeconds - 4 * 3600);
    expect(toChartPoints(bars, "1M", "America/New_York")[0].time).toBe(utcSeconds);
  });

  it("computes the change across a range", () => {
    expect(rangeChange([bar("a", "100"), bar("b", "110")])).toEqual({ change: 10, changePct: 10 });
    expect(rangeChange([bar("a", "100")])).toBeNull();
  });
});

describe("formatMoney", () => {
  it("always uses two decimals, even for small amounts", () => {
    expect(formatMoney("0", "USD")).toMatch(/0\.00$/);
    expect(formatMoney("0.5", "USD")).toMatch(/0\.50$/);
    expect(formatMoney("100000", "USD")).toContain("100,000.00");
  });
});

describe("apiRequest", () => {
  it("accepts empty success bodies (202/204) and rejects malformed JSON clearly", async () => {
    const { apiRequest, ApiError } = await import("@/lib/api");
    vi.stubGlobal("fetch", vi.fn(async () => new Response("", { status: 202 })));
    await expect(apiRequest("/api/v1/brief/generate", { method: "POST" })).resolves.toBeUndefined();
    vi.stubGlobal("fetch", vi.fn(async () => new Response(null, { status: 204 })));
    await expect(apiRequest("/x", { method: "DELETE" })).resolves.toBeUndefined();
    vi.stubGlobal("fetch", vi.fn(async () => new Response("<html>", { status: 200 })));
    await expect(apiRequest("/x")).rejects.toBeInstanceOf(ApiError);
  });
});

describe("serverApiBaseUrl", () => {
  it("avoids the slow localhost lookup for server-side fetches", async () => {
    const { serverApiBaseUrl } = await import("@/lib/api");
    expect(serverApiBaseUrl("http://localhost:8000", undefined)).toBe("http://127.0.0.1:8000");
    expect(serverApiBaseUrl("http://localhost", undefined)).toBe("http://127.0.0.1");
    expect(serverApiBaseUrl("https://api.example.com", undefined)).toBe("https://api.example.com");
    expect(serverApiBaseUrl("http://localhostish.dev:8000", undefined)).toBe("http://localhostish.dev:8000");
    expect(serverApiBaseUrl("http://localhost:8000", "http://backend:8000")).toBe("http://backend:8000");
  });
});

describe("same-origin API (Vercel proxy)", () => {
  it("needs API_BASE_URL on the server and lets live prices bypass the proxy", async () => {
    const { serverApiBaseUrl, streamUrl } = await import("@/lib/api");
    expect(serverApiBaseUrl("", "https://marketpulse-api.onrender.com/")).toBe("https://marketpulse-api.onrender.com");
    expect(() => serverApiBaseUrl("", undefined)).toThrow(/API_BASE_URL must be set/);
    expect(streamUrl(["AAPL", "OANDA:XAU_USD"], "https://marketpulse-api.onrender.com")).toBe(
      "https://marketpulse-api.onrender.com/api/v1/stream?symbols=AAPL,OANDA%3AXAU_USD",
    );
  });
});

describe("toSettled (cached error carrier)", () => {
  it("passes data through on success", () => {
    const r = toSettled({ ok: true, value: { hello: "world" } });
    expect(r).toEqual({ data: { hello: "world" }, error: null });
  });

  it("rebuilds the ApiError so the backend's code and message survive the cache boundary", () => {
    // Regression guard: a thrown ApiError gets redacted crossing `use cache`, which turned specific
    // errors (e.g. no_data → "No company profile available") into a generic "something went wrong".
    const r = toSettled({ ok: false, error: { message: "No data available for this request.", status: 404, code: "no_data" } });
    expect(r.data).toBeNull();
    expect(r.error?.message).toBe("No data available for this request.");
    expect(r.error?.code).toBe("no_data");
    expect(r.error?.status).toBe(404);
    expect(r.error?.retryable).toBe(false); // 404/no_data must not offer a pointless retry
  });

  it("keeps transient failures retryable", () => {
    const r = toSettled({ ok: false, error: { message: "Server trouble", status: 503, code: "unknown" } });
    expect(r.error?.retryable).toBe(true);
  });
});

describe("chart indicators", () => {
  const points = [10, 20, 30, 40, 50].map((value, i) => ({ time: i, value }));

  it("computes a simple moving average from the period-th bar on", () => {
    expect(sma(points, 3)).toEqual([
      { time: 2, value: 20 },
      { time: 3, value: 30 },
      { time: 4, value: 40 },
    ]);
    expect(sma(points, 5)).toEqual([{ time: 4, value: 30 }]);
  });

  it("returns nothing rather than back-filling when history is too short", () => {
    expect(sma(points, 6)).toEqual([]);
    expect(sma([], 20)).toEqual([]);
  });

  it("indexes a series to percent change from its first value", () => {
    expect(toPerformance(points).map((p) => p.value)).toEqual([0, 100, 200, 300, 400]);
    expect(toPerformance([])).toEqual([]);
    expect(toPerformance([{ time: 0, value: 0 }])).toEqual([]);
  });

  it("maps bars to candles and to volume, skipping bars without volume", () => {
    const ohlc = (timestamp: string, open: string, close: string, volume: number | null): Bar => ({
      timestamp, open, high: "12", low: "8", close, volume,
    });
    const bars = [ohlc("2026-10-15T00:00:00Z", "10", "11", 500), ohlc("2026-10-16T00:00:00Z", "11", "9", null)];
    expect(toCandlePoints(bars, "1M", null)[0]).toMatchObject({ open: 10, high: 12, low: 8, close: 11 });
    expect(toVolumePoints(bars, "1M", null)).toEqual([{ time: Date.UTC(2026, 9, 15) / 1000, value: 500, up: true }]);
  });
});

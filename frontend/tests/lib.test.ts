import { describe, expect, it } from "vitest";

import { rangeChange, toChartPoints, tzOffsetSeconds } from "@/lib/chart";
import { direction, formatChange, formatCompact, formatCountdown, formatPct, formatPrice } from "@/lib/format";
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

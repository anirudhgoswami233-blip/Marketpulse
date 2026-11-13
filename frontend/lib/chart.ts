import type { Bar, ChartRange } from "@/types/api";

export const CHART_RANGES: ChartRange[] = ["1D", "1W", "1M", "1Y", "5Y"];

export const INTRADAY_RANGES = new Set<ChartRange>(["1D", "1W"]);

/** Moving-average overlays offered on the price chart: period in bars → series colour token. */
export const SMA_OVERLAYS = [
  { period: 20, token: "--series-2" },
  { period: 50, token: "--series-3" },
  { period: 200, token: "--series-4" },
] as const;

/** Offset of `timeZone` from UTC at `date`, in seconds (e.g. -14400 for New York in summer). */
export function tzOffsetSeconds(date: Date, timeZone: string): number {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone,
    hourCycle: "h23",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).formatToParts(date);
  const get = (type: string) => Number(parts.find((p) => p.type === type)?.value);
  const asUtc = Date.UTC(get("year"), get("month") - 1, get("day"), get("hour"), get("minute"), get("second"));
  return Math.round((asUtc - date.getTime()) / 1000);
}

export interface ChartPoint {
  /** Seconds. Intraday points are shifted so the chart's UTC axis reads in exchange-local time. */
  time: number;
  value: number;
}

export interface CandlePoint {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
}

export interface VolumePoint extends ChartPoint {
  /** True when the bar closed at or above its open (drawn in the "up" colour). */
  up: boolean;
}

/** Chart-axis time for a bar: UTC seconds, shifted to exchange-local time on intraday ranges. */
function barTime(bar: Bar, range: ChartRange, timeZone: string | null): number {
  const date = new Date(bar.timestamp);
  const seconds = Math.floor(date.getTime() / 1000);
  return INTRADAY_RANGES.has(range) && timeZone ? seconds + tzOffsetSeconds(date, timeZone) : seconds;
}

export function toChartPoints(bars: Bar[], range: ChartRange, timeZone: string | null): ChartPoint[] {
  return bars
    .map((bar) => ({ time: barTime(bar, range, timeZone), value: Number(bar.close) }))
    .filter((p) => Number.isFinite(p.value));
}

export function toCandlePoints(bars: Bar[], range: ChartRange, timeZone: string | null): CandlePoint[] {
  return bars
    .map((bar) => ({
      time: barTime(bar, range, timeZone),
      open: Number(bar.open),
      high: Number(bar.high),
      low: Number(bar.low),
      close: Number(bar.close),
    }))
    .filter((c) => [c.open, c.high, c.low, c.close].every(Number.isFinite));
}

/** Bars with a reported volume. Empty when the provider sends none (e.g. forex). */
export function toVolumePoints(bars: Bar[], range: ChartRange, timeZone: string | null): VolumePoint[] {
  return bars
    .filter((bar) => bar.volume !== null && bar.volume > 0)
    .map((bar) => ({
      time: barTime(bar, range, timeZone),
      value: bar.volume as number,
      up: Number(bar.close) >= Number(bar.open),
    }));
}

/**
 * Simple moving average: the mean of the last `period` values, one point per bar from the `period`-th on.
 * Fewer than `period` points gives an empty series; nothing is back-filled.
 */
export function sma(points: ChartPoint[], period: number): ChartPoint[] {
  if (period < 1 || points.length < period) return [];
  const out: ChartPoint[] = [];
  let sum = 0;
  for (let i = 0; i < points.length; i++) {
    sum += points[i].value;
    if (i >= period) sum -= points[i - period].value;
    if (i >= period - 1) out.push({ time: points[i].time, value: sum / period });
  }
  return out;
}

export function rangeChange(bars: Bar[]): { change: number; changePct: number } | null {
  if (bars.length < 2) return null;
  const first = Number(bars[0].close);
  const last = Number(bars[bars.length - 1].close);
  if (!first) return null;
  return { change: last - first, changePct: ((last - first) / first) * 100 };
}

/**
 * Percent change of each point from the series' first value, so symbols at different prices share one
 * axis. Empty if the series is empty or starts at zero.
 */
export function toPerformance(points: ChartPoint[]): ChartPoint[] {
  const base = points[0]?.value;
  if (!base) return [];
  return points.map((p) => ({ time: p.time, value: ((p.value - base) / base) * 100 }));
}

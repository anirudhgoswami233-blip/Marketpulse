import type { Bar, ChartRange } from "@/types/api";

export const CHART_RANGES: ChartRange[] = ["1D", "1W", "1M", "1Y", "5Y"];

export const INTRADAY_RANGES = new Set<ChartRange>(["1D", "1W"]);

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

export function toChartPoints(bars: Bar[], range: ChartRange, timeZone: string | null): ChartPoint[] {
  const shift = INTRADAY_RANGES.has(range) && timeZone;
  return bars
    .map((bar) => {
      const date = new Date(bar.timestamp);
      const seconds = Math.floor(date.getTime() / 1000);
      return {
        time: shift ? seconds + tzOffsetSeconds(date, timeZone) : seconds,
        value: Number(bar.close),
      };
    })
    .filter((p) => Number.isFinite(p.value));
}

export function rangeChange(bars: Bar[]): { change: number; changePct: number } | null {
  if (bars.length < 2) return null;
  const first = Number(bars[0].close);
  const last = Number(bars[bars.length - 1].close);
  if (!first) return null;
  return { change: last - first, changePct: ((last - first) / first) * 100 };
}

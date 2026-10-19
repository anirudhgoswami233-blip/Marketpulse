"use client";

import { LineSeries, createChart, type IChartApi, type ISeriesApi } from "lightweight-charts";
import { useEffect, useRef, useState } from "react";

import { formatDate } from "@/lib/format";
import { subscribeTheme } from "@/lib/theme";

export interface LinePoint {
  date: string; // YYYY-MM-DD
  value: number;
}

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/**
 * One series on one axis (the card title names it, so no legend). Hover shows the date and value; a data
 * table sits behind a disclosure for screen readers and exact values.
 */
export function MiniLineChart({ points, unit, label }: { points: LinePoint[]; unit: string; label: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<LinePoint | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || points.length === 0) return;
    const theme = () => ({
      layout: { background: { color: "transparent" }, textColor: cssVar("--text-secondary"), fontSize: 11 },
      grid: { vertLines: { visible: false }, horzLines: { color: cssVar("--chart-grid") } },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false },
    });
    const chart: IChartApi = createChart(container, {
      ...theme(),
      autoSize: true,
      height: 140,
      handleScroll: false,
      handleScale: false,
    });
    const series: ISeriesApi<"Line"> = chart.addSeries(LineSeries, {
      color: cssVar("--chart-line"),
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    series.setData(points.map((p) => ({ time: p.date, value: p.value })));
    chart.timeScale().fitContent();
    chart.subscribeCrosshairMove((param) => {
      const point = param.seriesData.get(series);
      if (!param.time || !point || !("value" in point)) {
        setHover(null);
        return;
      }
      setHover({ date: String(param.time), value: point.value });
    });
    const unsubscribe = subscribeTheme(() => {
      chart.applyOptions(theme());
      series.applyOptions({ color: cssVar("--chart-line") });
    });
    return () => {
      unsubscribe();
      chart.remove();
    };
  }, [points]);

  return (
    <div>
      <p className="tabular h-4 text-xs text-secondary" aria-live="polite">
        {hover ? `${formatDate(hover.date)}: ${hover.value.toFixed(2)}${unit === "%" ? "%" : ` ${unit}`}` : ""}
      </p>
      <div ref={containerRef} className="h-[140px] w-full" data-testid={`chart-${label}`} />
      <details className="mt-1 text-xs text-secondary">
        <summary className="cursor-pointer">Data table</summary>
        <table className="mt-1 w-full">
          <caption className="sr-only">{label}, most recent first</caption>
          <tbody>
            {points
              .slice(-24)
              .reverse()
              .map((p) => (
                <tr key={p.date}>
                  <td>{formatDate(p.date)}</td>
                  <td className="tabular text-right">{p.value.toFixed(2)}</td>
                </tr>
              ))}
          </tbody>
        </table>
      </details>
    </div>
  );
}

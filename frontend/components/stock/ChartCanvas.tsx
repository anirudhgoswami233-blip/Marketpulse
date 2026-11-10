"use client";

import { LineSeries, createChart, type IChartApi, type ISeriesApi, type UTCTimestamp } from "lightweight-charts";
import { useEffect, useRef, useState } from "react";

import { INTRADAY_RANGES, toChartPoints } from "@/lib/chart";
import { chartThemeOptions, lineSeriesOptions } from "@/lib/chartTheme";
import { formatPrice } from "@/lib/format";
import { subscribeTheme } from "@/lib/theme";
import type { Chart } from "@/types/api";

/** The chart itself. Loaded on demand by PriceChart so the charting library stays out of the page bundle. */
export default function ChartCanvas({ chart, currency }: { chart: Chart; currency: string | null }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<{ label: string; value: number } | null>(null);
  const intraday = INTRADAY_RANGES.has(chart.range);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const theme = () => {
      const base = chartThemeOptions();
      return { ...base, timeScale: { ...base.timeScale, timeVisible: intraday, secondsVisible: false } };
    };
    const instance: IChartApi = createChart(container, {
      ...theme(),
      autoSize: true,
      height: 288,
      handleScroll: false,
      handleScale: false,
    });
    const series: ISeriesApi<"Line"> = instance.addSeries(LineSeries, { ...lineSeriesOptions(), lastValueVisible: true });
    series.setData(
      toChartPoints(chart.bars, chart.range, chart.timezone).map((p) => ({
        time: p.time as UTCTimestamp,
        value: p.value,
      })),
    );
    instance.timeScale().fitContent();

    instance.subscribeCrosshairMove((param) => {
      const point = param.seriesData.get(series);
      if (!param.time || !point || !("value" in point)) {
        setHover(null);
        return;
      }
      const date = new Date(Number(param.time) * 1000);
      const label = intraday
        ? date.toISOString().slice(0, 16).replace("T", " ")
        : date.toISOString().slice(0, 10);
      setHover({ label, value: point.value });
    });

    // Restyle when the user toggles the theme or the OS switches between light and dark.
    const unsubscribeTheme = subscribeTheme(() => {
      instance.applyOptions(theme());
      series.applyOptions(lineSeriesOptions());
    });

    return () => {
      unsubscribeTheme();
      instance.remove();
    };
  }, [chart, intraday]);

  const recent = chart.bars.slice(-30).reverse();
  return (
    <div>
      <p className="tabular h-5 text-xs text-secondary" aria-live="polite">
        {hover ? (
          <>
            {hover.label}
            {intraday && chart.timezone ? ` (${chart.timezone})` : ""} · {formatPrice(hover.value, currency)}
          </>
        ) : (
          <span className="text-muted">Hover the chart for prices</span>
        )}
      </p>
      <div ref={containerRef} className="h-72 w-full" data-testid="price-chart" />
      <details className="mt-2 text-xs text-secondary">
        <summary className="cursor-pointer">Show data table</summary>
        <table className="data-table mt-2 max-w-sm">
          <thead>
            <tr>
              <th scope="col">Time</th>
              <th scope="col" className="num">
                Close
              </th>
            </tr>
          </thead>
          <tbody>
            {recent.map((bar) => (
              <tr key={bar.timestamp}>
                <td>{intraday ? bar.timestamp.slice(0, 16).replace("T", " ") + " UTC" : bar.timestamp.slice(0, 10)}</td>
                <td className="num">{formatPrice(bar.close, currency)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </div>
  );
}

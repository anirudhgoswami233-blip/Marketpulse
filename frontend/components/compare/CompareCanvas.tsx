"use client";

import { LineSeries, createChart, type IChartApi, type ISeriesApi, type UTCTimestamp } from "lightweight-charts";
import { useEffect, useRef, useState } from "react";

import type { ChartPoint } from "@/lib/chart";
import { chartThemeOptions, tokenColor } from "@/lib/chartTheme";
import { formatPct } from "@/lib/format";
import { subscribeTheme } from "@/lib/theme";

export interface CompareSeries {
  symbol: string;
  /** Colour token from the validated series palette (assigned by position, never recycled). */
  token: string;
  /** Percent change from the first bar of the range. */
  points: ChartPoint[];
}

/** One line per symbol on a shared percent axis. Loaded on demand to keep the chart library off the page bundle. */
export default function CompareCanvas({ series }: { series: CompareSeries[] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<{ label: string; values: { symbol: string; value: number }[] } | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const instance: IChartApi = createChart(container, {
      ...chartThemeOptions(),
      autoSize: true,
      height: 320,
      handleScroll: false,
      handleScale: false,
      localization: { priceFormatter: (value: number) => formatPct(value) },
    });
    const lines = series.map((s) => {
      const line: ISeriesApi<"Line"> = instance.addSeries(LineSeries, {
        color: tokenColor(s.token),
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: true,
      });
      line.setData(s.points.map((p) => ({ time: p.time as UTCTimestamp, value: p.value })));
      return { s, line };
    });
    instance.timeScale().fitContent();

    instance.subscribeCrosshairMove((param) => {
      if (!param.time) {
        setHover(null);
        return;
      }
      const values = lines.flatMap(({ s, line }) => {
        const point = param.seriesData.get(line);
        return point && "value" in point ? [{ symbol: s.symbol, value: point.value }] : [];
      });
      setHover(values.length ? { label: new Date(Number(param.time) * 1000).toISOString().slice(0, 10), values } : null);
    });

    const unsubscribe = subscribeTheme(() => {
      instance.applyOptions(chartThemeOptions());
      for (const { s, line } of lines) line.applyOptions({ color: tokenColor(s.token) });
    });
    return () => {
      unsubscribe();
      instance.remove();
    };
  }, [series]);

  return (
    <div>
      <p className="tabular h-5 truncate text-xs text-secondary" aria-live="polite">
        {hover ? (
          <>
            {hover.label} · {hover.values.map((v) => `${v.symbol} ${formatPct(v.value)}`).join(" · ")}
          </>
        ) : (
          <span className="text-muted">Hover the chart to read each symbol&apos;s change since the start of the range</span>
        )}
      </p>
      <div ref={containerRef} className="h-80 w-full" data-testid="compare-chart" />
    </div>
  );
}

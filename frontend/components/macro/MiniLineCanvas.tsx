"use client";

import { LineSeries, createChart, type IChartApi, type ISeriesApi } from "lightweight-charts";
import { useEffect, useRef, useState } from "react";

import type { LinePoint } from "@/components/macro/MiniLineChart";
import { chartThemeOptions, lineSeriesOptions } from "@/lib/chartTheme";
import { formatDate } from "@/lib/format";
import { subscribeTheme } from "@/lib/theme";

/** The canvas half of MiniLineChart, loaded on demand so the charting library stays out of the page bundle. */
export default function MiniLineCanvas({ points, unit, label }: { points: LinePoint[]; unit: string; label: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<LinePoint | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || points.length === 0) return;
    const chart: IChartApi = createChart(container, {
      ...chartThemeOptions(),
      autoSize: true,
      height: 140,
      handleScroll: false,
      handleScale: false,
    });
    const series: ISeriesApi<"Line"> = chart.addSeries(LineSeries, { ...lineSeriesOptions(), lastValueVisible: false });
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
      chart.applyOptions(chartThemeOptions());
      series.applyOptions(lineSeriesOptions());
    });
    return () => {
      unsubscribe();
      chart.remove();
    };
  }, [points]);

  return (
    <>
      <p className="tabular h-4 text-xs text-secondary" aria-live="polite">
        {hover ? `${formatDate(hover.date)}: ${hover.value.toFixed(2)}${unit === "%" ? "%" : ` ${unit}`}` : ""}
      </p>
      <div ref={containerRef} className="h-[140px] w-full" data-testid={`chart-${label}`} />
    </>
  );
}

"use client";

import { AreaSeries, createChart, type IChartApi, type ISeriesApi, type UTCTimestamp } from "lightweight-charts";
import { useEffect, useRef, useState } from "react";

import { ChangeText, EmptyState, Skeleton } from "@/components/ui/primitives";
import { ErrorState, StaleBadge } from "@/components/ui/status";
import { api, toApiError, type ApiError } from "@/lib/api";
import { CHART_RANGES, INTRADAY_RANGES, rangeChange, toChartPoints } from "@/lib/chart";
import { formatPrice } from "@/lib/format";
import type { Chart, ChartRange, Envelope } from "@/types/api";

type Result = { kind: "ready"; chart: Envelope<Chart> } | { kind: "error"; error: ApiError };
type State = { kind: "loading" } | Result;

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

export function PriceChart({ symbol, currency }: { symbol: string; currency: string | null }) {
  const [range, setRange] = useState<ChartRange>("1M");
  const [retryToken, setRetryToken] = useState(0);
  // Results are tagged with the request they answer; anything else means that request is still loading.
  const requestKey = `${symbol}|${range}|${retryToken}`;
  const [result, setResult] = useState<{ key: string; value: Result } | null>(null);
  const state: State = result?.key === requestKey ? result.value : { kind: "loading" };

  useEffect(() => {
    const controller = new AbortController();
    api
      .chart(symbol, range, { signal: controller.signal })
      .then((chart) => setResult({ key: requestKey, value: { kind: "ready", chart } }))
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setResult({ key: requestKey, value: { kind: "error", error: toApiError(error) } });
        }
      });
    return () => controller.abort();
  }, [symbol, range, requestKey]);

  const bars = state.kind === "ready" ? state.chart.data.bars : [];
  // On 1D the header already shows the day's change vs the previous close; a first-bar-to-last-bar
  // figure would contradict it, so only show the range change for longer ranges.
  const change = range === "1D" ? null : rangeChange(bars);

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div role="tablist" aria-label="Chart range" className="flex gap-1">
          {CHART_RANGES.map((r) => (
            <button
              key={r}
              role="tab"
              type="button"
              aria-selected={r === range}
              onClick={() => setRange(r)}
              className={`rounded-md px-2.5 py-1 text-xs font-medium ${
                r === range ? "bg-accent text-surface" : "text-secondary hover:bg-surface-2"
              }`}
            >
              {r}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2 text-xs">
          {change && <ChangeText change={change.change.toFixed(2)} changePct={change.changePct.toFixed(4)} />}
          {state.kind === "ready" && <StaleBadge asOf={state.chart.as_of} stale={state.chart.stale} />}
        </div>
      </div>

      {state.kind === "loading" && (
        <div role="status" aria-label="Loading chart">
          <Skeleton className="h-72 w-full" />
        </div>
      )}
      {state.kind === "error" && (
        <ErrorState
          message={
            state.error.code === "unavailable"
              ? "Price history for this symbol isn't available on our current data plan."
              : state.error.message
          }
          retryable={state.error.retryable}
          onRetry={() => setRetryToken((n) => n + 1)}
        />
      )}
      {state.kind === "ready" && bars.length === 0 && (
        <EmptyState title="No price history for this range">Try a longer range.</EmptyState>
      )}
      {state.kind === "ready" && bars.length > 0 && (
        <ChartCanvas chart={state.chart.data} currency={currency} />
      )}
    </div>
  );
}

function ChartCanvas({ chart, currency }: { chart: Chart; currency: string | null }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<{ label: string; value: number } | null>(null);
  const intraday = INTRADAY_RANGES.has(chart.range);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const theme = () => ({
      layout: { background: { color: "transparent" }, textColor: cssVar("--text-secondary") },
      grid: { vertLines: { visible: false }, horzLines: { color: cssVar("--chart-grid") } },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false, timeVisible: intraday, secondsVisible: false },
    });
    const instance: IChartApi = createChart(container, {
      ...theme(),
      autoSize: true,
      height: 288,
      crosshair: { mode: 0 },
      handleScroll: false,
      handleScale: false,
    });
    const series: ISeriesApi<"Area"> = instance.addSeries(AreaSeries, {
      lineColor: cssVar("--chart-line"),
      topColor: cssVar("--chart-fill"),
      bottomColor: "rgba(0,0,0,0)",
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: true,
    });
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

    // Restyle when the user toggles light/dark mode.
    const observer = new MutationObserver(() => {
      instance.applyOptions(theme());
      series.applyOptions({ lineColor: cssVar("--chart-line"), topColor: cssVar("--chart-fill") });
    });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

    return () => {
      observer.disconnect();
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
        <table className="mt-2 w-full">
          <thead>
            <tr className="text-left text-muted">
              <th scope="col" className="font-normal">
                Time
              </th>
              <th scope="col" className="text-right font-normal">
                Close
              </th>
            </tr>
          </thead>
          <tbody>
            {recent.map((bar) => (
              <tr key={bar.timestamp}>
                <td>{intraday ? bar.timestamp.slice(0, 16).replace("T", " ") + " UTC" : bar.timestamp.slice(0, 10)}</td>
                <td className="tabular text-right">{formatPrice(bar.close, currency)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </div>
  );
}

"use client";

import dynamic from "next/dynamic";
import { useEffect, useRef, useState } from "react";

import { ChangeText, EmptyState, Skeleton } from "@/components/ui/primitives";
import { ErrorState, StaleBadge } from "@/components/ui/status";
import { api, toApiError, type ApiError } from "@/lib/api";
import type { ChartMode } from "@/components/stock/ChartCanvas";
import { CHART_RANGES, SMA_OVERLAYS, rangeChange } from "@/lib/chart";
import type { Chart, ChartRange, Envelope } from "@/types/api";

type Result = { kind: "ready"; chart: Envelope<Chart> } | { kind: "error"; error: ApiError };
type State = { kind: "loading" } | Result;

/** Same footprint as the rendered chart (hover line + canvas), so swapping it in doesn't shift the page. */
function ChartSkeleton() {
  return (
    <div role="status" aria-label="Loading chart">
      <div className="h-5" />
      <Skeleton className="h-72 w-full" />
    </div>
  );
}

// The charting library is ~50 kB gzipped: fetch it in parallel with the price history, off the page bundle.
const ChartCanvas = dynamic(() => import("@/components/stock/ChartCanvas"), { ssr: false, loading: ChartSkeleton });

export function PriceChart({
  symbol,
  currency,
  initialChart,
}: {
  symbol: string;
  currency: string | null;
  /** Server-cached history for the default "1M" range, so the first paint doesn't wait on the backend. */
  initialChart?: Envelope<Chart>;
}) {
  const [range, setRange] = useState<ChartRange>("1M");
  const [retryToken, setRetryToken] = useState(0);
  const [mode, setMode] = useState<ChartMode>("line");
  const [overlays, setOverlays] = useState<number[]>([]);
  const [showVolume, setShowVolume] = useState(false);
  // Results are tagged with the request they answer; anything else means that request is still loading.
  const requestKey = `${symbol}|${range}|${retryToken}`;
  const seededKey = `${symbol}|1M|0`;
  const [result, setResult] = useState<{ key: string; value: Result } | null>(
    initialChart ? { key: seededKey, value: { kind: "ready", chart: initialChart } } : null,
  );
  // The seeded range is already drawn from server cache; skip its fetch, but refetch on a range switch or retry.
  const skipFetchFor = useRef<string | null>(initialChart ? seededKey : null);
  const state: State = result?.key === requestKey ? result.value : { kind: "loading" };

  useEffect(() => {
    if (skipFetchFor.current === requestKey) {
      skipFetchFor.current = null;
      return;
    }
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
  const hasVolume = bars.some((bar) => bar.volume !== null && bar.volume > 0);
  const toggleOverlay = (period: number) =>
    setOverlays((current) => (current.includes(period) ? current.filter((p) => p !== period) : [...current, period]));

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div role="tablist" aria-label="Chart range" className="flex gap-0.5">
          {CHART_RANGES.map((r) => (
            <button
              key={r}
              role="tab"
              type="button"
              aria-selected={r === range}
              onClick={() => setRange(r)}
              className="tab tabular"
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

      {/* Chart tools. The moving-average buttons double as the legend: each carries its line's colour. */}
      <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1">
        <div role="group" aria-label="Chart type" className="flex gap-0.5">
          {(["line", "candles"] as const).map((m) => (
            <button key={m} type="button" aria-pressed={mode === m} onClick={() => setMode(m)} className="tab capitalize">
              {m}
            </button>
          ))}
        </div>
        <div role="group" aria-label="Indicators" className="flex flex-wrap gap-0.5">
          {SMA_OVERLAYS.map(({ period, token }) => {
            const enough = bars.length >= period;
            return (
              <button
                key={period}
                type="button"
                aria-pressed={overlays.includes(period)}
                disabled={state.kind === "ready" && !enough}
                title={
                  enough
                    ? `${period}-bar simple moving average`
                    : `Needs at least ${period} bars; this range has ${bars.length}. Try a longer range.`
                }
                onClick={() => toggleOverlay(period)}
                className="tab tabular inline-flex items-center gap-1 disabled:opacity-50"
              >
                <span aria-hidden className="inline-block h-0.5 w-3" style={{ background: `var(${token})` }} />
                SMA {period}
              </button>
            );
          })}
          <button
            type="button"
            aria-pressed={showVolume}
            disabled={state.kind === "ready" && !hasVolume}
            title={hasVolume ? "Traded volume per bar" : "No volume is reported for this symbol"}
            onClick={() => setShowVolume((v) => !v)}
            className="tab disabled:opacity-50"
          >
            Volume
          </button>
        </div>
      </div>

      {state.kind === "loading" && <ChartSkeleton />}
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
        <ChartCanvas
          chart={state.chart.data}
          currency={currency}
          mode={mode}
          overlays={overlays.filter((period) => bars.length >= period)}
          showVolume={showVolume && hasVolume}
        />
      )}
    </div>
  );
}

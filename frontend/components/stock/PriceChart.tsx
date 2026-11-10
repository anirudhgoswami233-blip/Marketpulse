"use client";

import dynamic from "next/dynamic";
import { useEffect, useRef, useState } from "react";

import { ChangeText, EmptyState, Skeleton } from "@/components/ui/primitives";
import { ErrorState, StaleBadge } from "@/components/ui/status";
import { api, toApiError, type ApiError } from "@/lib/api";
import { CHART_RANGES, rangeChange } from "@/lib/chart";
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
        <ChartCanvas chart={state.chart.data} currency={currency} />
      )}
    </div>
  );
}

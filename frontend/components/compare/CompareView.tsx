"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import type { CompareSeries } from "@/components/compare/CompareCanvas";
import { SearchBox } from "@/components/search/SearchBox";
import { Card, ChangeText, EmptyState, Skeleton } from "@/components/ui/primitives";
import { StaleBadge } from "@/components/ui/status";
import { api, toApiError, type ApiError } from "@/lib/api";
import { rangeChange, toChartPoints, toPerformance } from "@/lib/chart";
import { formatDate, formatPrice } from "@/lib/format";
import type { Chart, ChartRange, Envelope, SymbolInfo } from "@/types/api";

export const MAX_SYMBOLS = 4;
/** Daily ranges only: they share one stored price history per symbol, so switching range costs no extra data. */
export const COMPARE_RANGES: ChartRange[] = ["1M", "1Y", "5Y"];
const SERIES_TOKENS = ["--series-1", "--series-2", "--series-3", "--series-4"];
const SYMBOL_PATTERN = /^[A-Za-z0-9.:_\-^]{1,32}$/;

type Loaded = { kind: "ready"; chart: Envelope<Chart> } | { kind: "error"; error: ApiError };

function CanvasSkeleton() {
  return (
    <div role="status" aria-label="Loading comparison chart">
      <div className="h-5" />
      <Skeleton className="h-80 w-full" />
    </div>
  );
}

const CompareCanvas = dynamic(() => import("@/components/compare/CompareCanvas"), { ssr: false, loading: CanvasSkeleton });

/** Symbols from `?symbols=A,B`: upper-cased, de-duplicated, valid ones only, at most four. */
export function parseSymbols(raw: string | null): string[] {
  if (!raw) return [];
  const symbols = raw
    .split(",")
    .map((s) => s.trim().toUpperCase())
    .filter((s) => SYMBOL_PATTERN.test(s));
  return [...new Set(symbols)].slice(0, MAX_SYMBOLS);
}

export function CompareView() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const symbols = useMemo(() => parseSymbols(searchParams.get("symbols")), [searchParams]);
  const [range, setRange] = useState<ChartRange>("1Y");
  // Results are keyed by "symbol|range"; a missing key means that request is still in flight.
  const [results, setResults] = useState<Record<string, Loaded>>({});

  const setSymbols = (next: string[]) => {
    const query = next.length ? `?symbols=${next.map(encodeURIComponent).join(",")}` : "";
    router.replace(`${pathname ?? "/compare"}${query}`, { scroll: false });
  };

  const symbolsKey = symbols.join(",");
  useEffect(() => {
    const controller = new AbortController();
    for (const symbol of symbolsKey ? symbolsKey.split(",") : []) {
      const key = `${symbol}|${range}`;
      api
        .chart(symbol, range, { signal: controller.signal })
        .then((chart) => setResults((current) => ({ ...current, [key]: { kind: "ready", chart } })))
        .catch((error: unknown) => {
          if (!controller.signal.aborted) {
            setResults((current) => ({ ...current, [key]: { kind: "error", error: toApiError(error) } }));
          }
        });
    }
    return () => controller.abort();
  }, [symbolsKey, range]);

  const rows = symbols.map((symbol, index) => ({
    symbol,
    token: SERIES_TOKENS[index],
    result: results[`${symbol}|${range}`] as Loaded | undefined,
  }));
  const loading = rows.some((row) => row.result === undefined);
  const series: CompareSeries[] = useMemo(
    () =>
      rows.flatMap((row) => {
        if (row.result?.kind !== "ready") return [];
        const { bars, timezone } = row.result.chart.data;
        const points = toPerformance(toChartPoints(bars, range, timezone));
        return points.length ? [{ symbol: row.symbol, token: row.token, points }] : [];
      }),
    // Rebuild only when the underlying results change, not on every render (the canvas redraws on identity).
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [symbolsKey, range, results],
  );

  const add = (info: SymbolInfo) => {
    if (!symbols.includes(info.symbol) && symbols.length < MAX_SYMBOLS) setSymbols([...symbols, info.symbol]);
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="w-full max-w-xs">
          {symbols.length < MAX_SYMBOLS ? (
            <SearchBox onSelect={add} placeholder="Add a symbol to compare…" label="Add a symbol to compare" />
          ) : (
            <p className="text-xs text-muted">Up to {MAX_SYMBOLS} symbols. Remove one to add another.</p>
          )}
        </div>
        <div role="tablist" aria-label="Comparison range" className="flex gap-0.5">
          {COMPARE_RANGES.map((r) => (
            <button key={r} type="button" role="tab" aria-selected={r === range} onClick={() => setRange(r)} className="tab tabular">
              {r}
            </button>
          ))}
        </div>
      </div>

      {symbols.length === 0 ? (
        <EmptyState title="Add symbols to compare">
          Search above to chart up to {MAX_SYMBOLS} stocks or ETFs against each other, each shown as percent change from the
          start of the range.
        </EmptyState>
      ) : (
        <>
          <Card title={`Performance · ${range}`}>
            {loading && series.length === 0 ? (
              <CanvasSkeleton />
            ) : series.length === 0 ? (
              <EmptyState title="No price history to chart">None of these symbols has history for this range.</EmptyState>
            ) : (
              <CompareCanvas series={series} />
            )}
          </Card>

          <Card title="Symbols" flush>
            <div className="overflow-x-auto">
              <table className="data-table min-w-[34rem]">
                <caption className="sr-only">Compared symbols and their change over the selected range</caption>
                <thead>
                  <tr>
                    <th scope="col">Symbol</th>
                    <th scope="col">From</th>
                    <th scope="col" className="num">
                      Start
                    </th>
                    <th scope="col" className="num">
                      Latest
                    </th>
                    <th scope="col" className="num">
                      Change
                    </th>
                    <th scope="col" className="num">
                      <span className="sr-only">Actions</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => {
                    const chart = row.result?.kind === "ready" ? row.result.chart : null;
                    const bars = chart?.data.bars ?? [];
                    const change = rangeChange(bars);
                    const currency = chart?.data.currency ?? null;
                    return (
                      <tr key={row.symbol}>
                        <td>
                          {/* The swatch is the chart legend: same colour as this symbol's line. */}
                          <span aria-hidden className="mr-1.5 inline-block h-0.5 w-3 align-middle" style={{ background: `var(${row.token})` }} />
                          <Link href={`/stock/${encodeURIComponent(row.symbol)}`} className="font-medium text-primary hover:text-accent">
                            {row.symbol}
                          </Link>
                          {chart && (
                            <span className="ml-1.5 align-middle">
                              <StaleBadge asOf={chart.as_of} stale={chart.stale} />
                            </span>
                          )}
                        </td>
                        {row.result === undefined ? (
                          <td colSpan={4} role="status" aria-label={`Loading ${row.symbol}`}>
                            <Skeleton className="ml-auto h-3.5 w-40" />
                          </td>
                        ) : row.result.kind === "error" ? (
                          <td colSpan={4} className="text-xs text-secondary">
                            {row.result.error.code === "unavailable" || row.result.error.code === "no_data"
                              ? "No price history on our current data plan"
                              : row.result.error.message}
                          </td>
                        ) : bars.length === 0 ? (
                          <td colSpan={4} className="text-xs text-secondary">
                            No price history for this range
                          </td>
                        ) : (
                          <>
                            <td className="text-xs whitespace-nowrap text-secondary">{formatDate(bars[0].timestamp.slice(0, 10))}</td>
                            <td className="num">{formatPrice(bars[0].close, currency)}</td>
                            <td className="num text-primary">{formatPrice(bars[bars.length - 1].close, currency)}</td>
                            <td className="num">{change ? <ChangeText changePct={change.changePct.toFixed(4)} /> : "—"}</td>
                          </>
                        )}
                        <td className="num">
                          <button
                            type="button"
                            onClick={() => setSymbols(symbols.filter((s) => s !== row.symbol))}
                            aria-label={`Remove ${row.symbol}`}
                            className="rounded-sm px-1.5 text-xs text-secondary hover:text-down"
                          >
                            Remove
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Card>
          <p className="text-xs text-muted">
            Change is measured from each symbol&apos;s first close in the range to its latest close, in its own currency. Past
            performance doesn&apos;t predict future returns.
          </p>
        </>
      )}
    </div>
  );
}

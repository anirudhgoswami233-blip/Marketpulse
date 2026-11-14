"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { DISCLAIMER, SignalBadge } from "@/components/signals/SignalCard";
import { Card, ChangeText, EmptyState } from "@/components/ui/primitives";
import { LocalTime, StaleBadge } from "@/components/ui/status";
import { formatCompact, formatNumber, formatPct, formatPrice } from "@/lib/format";
import { NO_FILTERS, PRESETS, filterRows, industries, sortRows, type Filters, type PresetId, type Sort, type SortKey } from "@/lib/screener";
import type { Screener, ScreenerRow, SignalLabel } from "@/types/api";

const SIGNALS: SignalLabel[] = ["Bullish signals", "Neutral", "Bearish signals"];

const COLUMNS: { key: SortKey; label: string; numeric: boolean; className?: string; title?: string }[] = [
  { key: "symbol", label: "Symbol", numeric: false },
  { key: "industry", label: "Industry", numeric: false, className: "max-lg:hidden" },
  { key: "price", label: "Price", numeric: true },
  { key: "change_pct", label: "Change", numeric: true },
  { key: "market_cap", label: "Mkt cap", numeric: true },
  { key: "pe_ttm", label: "P/E", numeric: true, title: "Trailing twelve-month price / earnings" },
  { key: "dividend_yield_pct", label: "Div yield", numeric: true, className: "max-md:hidden" },
  { key: "beta", label: "Beta", numeric: true, className: "max-md:hidden" },
  { key: "week52_position_pct", label: "52-wk range", numeric: true, title: "Where the price sits between its 52-week low and high" },
  { key: "signal_score", label: "Signal", numeric: false, title: "Latest technical signal label and score (−100 to +100)" },
];

function isSignalLabel(value: string | null): value is SignalLabel {
  return value !== null && (SIGNALS as string[]).includes(value);
}

/** Position in the 52-week range: a marker on a track, with the number beside it. */
function RangePosition({ row }: { row: ScreenerRow }) {
  if (row.week52_position_pct === null) return <span className="text-muted">—</span>;
  const position = Number(row.week52_position_pct);
  return (
    <span
      className="inline-flex items-center gap-1.5"
      title={`52-week range ${formatPrice(row.week52_low, row.currency)} – ${formatPrice(row.week52_high, row.currency)}`}
    >
      <span aria-hidden className="relative inline-block h-1 w-12 bg-surface-2">
        <span className="absolute -top-0.5 h-2 w-0.5 bg-primary" style={{ left: `calc(${position}% - 1px)` }} />
      </span>
      <span className="w-9 text-right">{formatNumber(position, 0)}%</span>
    </span>
  );
}

export function ScreenerView({ screener }: { screener: Screener }) {
  const [filters, setFilters] = useState<Filters>(NO_FILTERS);
  const [sort, setSort] = useState<Sort>({ key: "market_cap", descending: true });
  const rows = useMemo(() => sortRows(filterRows(screener.rows, filters), sort), [screener.rows, filters, sort]);
  const industryOptions = useMemo(() => industries(screener.rows), [screener.rows]);
  const filtered = filters !== NO_FILTERS && (filters.query.trim() || filters.signal || filters.industry || filters.presets.length > 0);

  const togglePreset = (id: PresetId) =>
    setFilters((f) => ({ ...f, presets: f.presets.includes(id) ? f.presets.filter((p) => p !== id) : [...f.presets, id] }));
  const sortBy = (key: SortKey) =>
    // Text columns start A→Z; numbers start with the largest, which is what a screen is usually for.
    setSort((s) => (s.key === key ? { key, descending: !s.descending } : { key, descending: key !== "symbol" && key !== "industry" }));

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
        {screener.quotes_as_of ? (
          <span>
            Prices updated <LocalTime iso={screener.quotes_as_of} />
          </span>
        ) : (
          <span role="status">Fetching the first price snapshot…</span>
        )}
        {screener.fundamentals_as_of && (
          <span>
            · fundamentals <LocalTime iso={screener.fundamentals_as_of} withDate />
          </span>
        )}
        <StaleBadge asOf={screener.quotes_as_of} stale={screener.stale} />
        {(screener.refreshing || screener.pending_fundamentals > 0) && (
          <span role="status">
            · loading fundamentals{screener.pending_fundamentals > 0 ? ` for ${screener.pending_fundamentals} more` : ""}; this page
            fills in over a few minutes
          </span>
        )}
      </div>

      <Card flush title="Filters" action={filtered ? <button type="button" className="btn" onClick={() => setFilters(NO_FILTERS)}>Reset filters</button> : undefined}>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 p-3">
          <input
            type="search"
            value={filters.query}
            onChange={(e) => setFilters((f) => ({ ...f, query: e.target.value }))}
            placeholder="Symbol or company"
            aria-label="Filter by symbol or company"
            className="input w-44 py-0.5 text-xs"
          />
          <label className="flex items-center gap-1.5 text-xs text-secondary">
            Industry
            <select
              value={filters.industry ?? ""}
              onChange={(e) => setFilters((f) => ({ ...f, industry: e.target.value || null }))}
              className="input w-auto py-0.5 text-xs"
            >
              <option value="">All</option>
              {industryOptions.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </label>
          <div role="group" aria-label="Signal" className="flex flex-wrap items-center gap-0.5">
            <span className="mr-1 text-xs text-secondary">Signal</span>
            <button type="button" className="tab" aria-pressed={filters.signal === null} onClick={() => setFilters((f) => ({ ...f, signal: null }))}>
              Any
            </button>
            {SIGNALS.map((label) => (
              <button key={label} type="button" className="tab" aria-pressed={filters.signal === label} onClick={() => setFilters((f) => ({ ...f, signal: label }))}>
                {label}
              </button>
            ))}
          </div>
          <div role="group" aria-label="Quick filters" className="flex flex-wrap gap-0.5">
            {PRESETS.map((preset) => (
              <button
                key={preset.id}
                type="button"
                className={`tab ${filters.presets.includes(preset.id) ? "" : "border-border"}`}
                aria-pressed={filters.presets.includes(preset.id)}
                title={preset.rule}
                onClick={() => togglePreset(preset.id)}
              >
                {preset.label}
              </button>
            ))}
          </div>
        </div>
      </Card>

      <Card flush title={`${rows.length} of ${screener.rows.length} stocks`}>
        {rows.length === 0 ? (
          <div className="p-3">
            <EmptyState title="No stocks match these filters">
              <button type="button" className="text-accent hover:underline" onClick={() => setFilters(NO_FILTERS)}>
                Reset filters
              </button>
            </EmptyState>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="data-table min-w-[44rem]">
              <caption className="sr-only">Screener results. Column headers sort the table.</caption>
              <thead>
                <tr>
                  {COLUMNS.map((column) => {
                    const active = sort.key === column.key;
                    return (
                      <th
                        key={column.key}
                        scope="col"
                        aria-sort={active ? (sort.descending ? "descending" : "ascending") : "none"}
                        className={`${column.numeric ? "num" : ""} ${column.className ?? ""}`}
                      >
                        <button
                          type="button"
                          onClick={() => sortBy(column.key)}
                          title={column.title}
                          className="inline-flex items-center gap-1 font-[inherit] tracking-[inherit] uppercase hover:text-primary"
                        >
                          {column.label}
                          <span aria-hidden className={`text-[0.7em] ${active ? "text-primary" : "opacity-0"}`}>
                            {sort.descending ? "▼" : "▲"}
                          </span>
                        </button>
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.symbol}>
                    <td className="max-w-52">
                      <Link href={`/stock/${encodeURIComponent(row.symbol)}`} className="font-medium text-primary hover:text-accent">
                        {row.display_symbol}
                      </Link>
                      <span className="block truncate text-2xs text-muted">{row.name}</span>
                    </td>
                    <td className="max-w-40 truncate text-xs text-secondary max-lg:hidden">{row.industry ?? "—"}</td>
                    <td className="num text-primary">{formatPrice(row.price, row.currency)}</td>
                    <td className="num">{row.change_pct === null ? <span className="text-muted">—</span> : <ChangeText changePct={row.change_pct} />}</td>
                    <td className="num">{formatCompact(row.market_cap, row.currency)}</td>
                    <td className="num">{formatNumber(row.pe_ttm)}</td>
                    <td className="num max-md:hidden">{row.dividend_yield_pct === null ? "—" : formatPct(row.dividend_yield_pct, false)}</td>
                    <td className="num max-md:hidden">{formatNumber(row.beta)}</td>
                    <td className="num">
                      <RangePosition row={row} />
                    </td>
                    <td>
                      {isSignalLabel(row.signal_label) ? (
                        <SignalBadge label={row.signal_label} score={row.signal_score ?? undefined} />
                      ) : (
                        <span className="text-xs text-muted" title="No signal computed for the latest session yet">
                          —
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <p className="text-xs text-muted">
        Covers the {screener.universe_size} large-cap US stocks we track. Fundamentals refresh about once a day; signals are based on
        the last completed session. {DISCLAIMER}
      </p>
    </div>
  );
}

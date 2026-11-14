// Pure filtering and sorting for the screener table (no I/O, so it's easy to test).

import type { ScreenerRow, SignalLabel } from "@/types/api";

export type SortKey =
  | "symbol"
  | "industry"
  | "price"
  | "change_pct"
  | "market_cap"
  | "pe_ttm"
  | "dividend_yield_pct"
  | "beta"
  | "week52_position_pct"
  | "signal_score";

export interface Sort {
  key: SortKey;
  descending: boolean;
}

/** Quick filters a trader reaches for first. Each is a plain, checkable rule shown in its tooltip. */
export const PRESETS = [
  { id: "near_high", label: "Near 52-week high", rule: "Price in the top 10% of its 52-week range" },
  { id: "near_low", label: "Near 52-week low", rule: "Price in the bottom 10% of its 52-week range" },
  { id: "gainers", label: "Up today", rule: "Positive change today" },
  { id: "losers", label: "Down today", rule: "Negative change today" },
  { id: "dividend", label: "Pays a dividend", rule: "Dividend yield above 0%" },
  { id: "low_pe", label: "P/E under 20", rule: "Trailing P/E between 0 and 20" },
] as const;

export type PresetId = (typeof PRESETS)[number]["id"];

export interface Filters {
  query: string;
  signal: SignalLabel | null;
  industry: string | null;
  presets: PresetId[];
}

export const NO_FILTERS: Filters = { query: "", signal: null, industry: null, presets: [] };

const num = (value: string | number | null): number | null => {
  if (value === null) return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
};

function matchesPreset(row: ScreenerRow, preset: PresetId): boolean {
  const position = num(row.week52_position_pct);
  const change = num(row.change_pct);
  const pe = num(row.pe_ttm);
  const dividend = num(row.dividend_yield_pct);
  switch (preset) {
    case "near_high":
      return position !== null && position >= 90;
    case "near_low":
      return position !== null && position <= 10;
    case "gainers":
      return change !== null && change > 0;
    case "losers":
      return change !== null && change < 0;
    case "dividend":
      return dividend !== null && dividend > 0;
    case "low_pe":
      return pe !== null && pe > 0 && pe < 20;
  }
}

/** Rows matching every active filter. A row missing the data a filter needs doesn't match it. */
export function filterRows(rows: ScreenerRow[], filters: Filters): ScreenerRow[] {
  const needle = filters.query.trim().toLowerCase();
  return rows.filter(
    (row) =>
      (!needle || row.symbol.toLowerCase().includes(needle) || row.name.toLowerCase().includes(needle)) &&
      (filters.signal === null || row.signal_label === filters.signal) &&
      (filters.industry === null || row.industry === filters.industry) &&
      filters.presets.every((preset) => matchesPreset(row, preset)),
  );
}

/** Sorted copy. Rows without a value for the sort column always go last, whichever the direction. */
export function sortRows(rows: ScreenerRow[], sort: Sort): ScreenerRow[] {
  const textKey = sort.key === "symbol" || sort.key === "industry";
  return [...rows].sort((a, b) => {
    const av = textKey ? a[sort.key] : num(a[sort.key] as string | number | null);
    const bv = textKey ? b[sort.key] : num(b[sort.key] as string | number | null);
    if (av === null && bv === null) return a.symbol.localeCompare(b.symbol);
    if (av === null) return 1;
    if (bv === null) return -1;
    const order = typeof av === "string" ? av.localeCompare(String(bv)) : (av as number) - (bv as number);
    return (sort.descending ? -order : order) || a.symbol.localeCompare(b.symbol);
  });
}

export function industries(rows: ScreenerRow[]): string[] {
  return [...new Set(rows.flatMap((row) => (row.industry ? [row.industry] : [])))].sort();
}

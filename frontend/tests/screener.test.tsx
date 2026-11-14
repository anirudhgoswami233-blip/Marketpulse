import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { parseSymbols } from "@/components/compare/CompareView";
import { ScreenerView } from "@/components/screener/ScreenerView";
import { AnalystRatings, EarningsHistory, consensusLabel } from "@/components/stock/StockAnalysis";
import { NO_FILTERS, filterRows, industries, sortRows } from "@/lib/screener";
import type { Screener, ScreenerRow } from "@/types/api";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  usePathname: () => "/compare",
  useSearchParams: () => new URLSearchParams(),
}));

function row(symbol: string, overrides: Partial<ScreenerRow> = {}): ScreenerRow {
  return {
    symbol,
    display_symbol: symbol,
    name: `${symbol} Corp`,
    industry: "Technology",
    currency: "USD",
    price: "100",
    change_pct: "1.5",
    market_cap: "1000000000",
    pe_ttm: "30",
    eps_ttm: "3",
    beta: "1.1",
    dividend_yield_pct: "0.5",
    week52_low: "80",
    week52_high: "120",
    week52_position_pct: "50",
    signal_label: "Neutral",
    signal_score: 5,
    signal_date: "2026-10-16",
    ...overrides,
  };
}

const ROWS = [
  row("AAA", { market_cap: "3000", change_pct: "2.0", week52_position_pct: "95", signal_label: "Bullish signals", signal_score: 45 }),
  row("BBB", { market_cap: "1000", change_pct: "-1.0", pe_ttm: "12", industry: "Banking", dividend_yield_pct: "0" }),
  row("CCC", { market_cap: null, change_pct: null, pe_ttm: null, week52_position_pct: null, signal_label: null, signal_score: null }),
];

const SCREENER: Screener = {
  rows: ROWS,
  universe_size: 30,
  pending_fundamentals: 0,
  refreshing: false,
  quotes_as_of: "2026-10-19T14:00:00Z",
  fundamentals_as_of: "2026-10-19T08:00:00Z",
  stale: false,
};

describe("screener filtering and sorting", () => {
  it("applies text, signal, industry and preset filters together", () => {
    expect(filterRows(ROWS, { ...NO_FILTERS, query: "bbb" }).map((r) => r.symbol)).toEqual(["BBB"]);
    expect(filterRows(ROWS, { ...NO_FILTERS, signal: "Bullish signals" }).map((r) => r.symbol)).toEqual(["AAA"]);
    expect(filterRows(ROWS, { ...NO_FILTERS, industry: "Banking" }).map((r) => r.symbol)).toEqual(["BBB"]);
    expect(filterRows(ROWS, { ...NO_FILTERS, presets: ["near_high", "gainers"] }).map((r) => r.symbol)).toEqual(["AAA"]);
    expect(filterRows(ROWS, { ...NO_FILTERS, presets: ["low_pe"] }).map((r) => r.symbol)).toEqual(["BBB"]);
    // A zero yield is not "pays a dividend".
    expect(filterRows(ROWS, { ...NO_FILTERS, presets: ["dividend"] }).map((r) => r.symbol)).toEqual(["AAA", "CCC"]);
    // A row with no change figure never matches a rule that needs one.
    expect(filterRows(ROWS, { ...NO_FILTERS, presets: ["losers"] }).map((r) => r.symbol)).toEqual(["BBB"]);
  });

  it("sorts numerically and always puts missing values last", () => {
    expect(sortRows(ROWS, { key: "market_cap", descending: true }).map((r) => r.symbol)).toEqual(["AAA", "BBB", "CCC"]);
    expect(sortRows(ROWS, { key: "market_cap", descending: false }).map((r) => r.symbol)).toEqual(["BBB", "AAA", "CCC"]);
    expect(sortRows(ROWS, { key: "symbol", descending: true }).map((r) => r.symbol)).toEqual(["CCC", "BBB", "AAA"]);
  });

  it("lists distinct industries", () => {
    expect(industries(ROWS)).toEqual(["Banking", "Technology"]);
  });
});

describe("ScreenerView", () => {
  it("shows every row, sorted by market cap, with signal badges and arrows", () => {
    render(<ScreenerView screener={SCREENER} />);
    const body = screen.getAllByRole("rowgroup")[1];
    const symbols = within(body)
      .getAllByRole("link")
      .map((a) => a.textContent);
    expect(symbols).toEqual(["AAA", "BBB", "CCC"]);
    expect(screen.getByText("3 of 3 stocks")).toBeTruthy();
    expect(within(body).getByText("Bullish signals")).toBeTruthy();
    expect(within(body).getAllByText("▼").length).toBeGreaterThan(0); // BBB is down: arrow, not colour alone
    expect(screen.getByText(/not financial advice/)).toBeTruthy();
  });

  it("filters by signal and quick filter, and offers a reset when nothing matches", () => {
    render(<ScreenerView screener={SCREENER} />);
    fireEvent.click(screen.getByRole("button", { name: "Bullish signals" }));
    expect(screen.getByText("1 of 3 stocks")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Down today" }));
    expect(screen.getByText("No stocks match these filters")).toBeTruthy();
    fireEvent.click(screen.getAllByRole("button", { name: "Reset filters" })[0]);
    expect(screen.getByText("3 of 3 stocks")).toBeTruthy();
  });

  it("re-sorts when a column header is clicked and exposes the sort to assistive tech", () => {
    render(<ScreenerView screener={SCREENER} />);
    const change = screen.getByRole("columnheader", { name: /Change/ });
    fireEvent.click(within(change).getByRole("button"));
    expect(change.getAttribute("aria-sort")).toBe("descending");
    const first = within(screen.getAllByRole("rowgroup")[1]).getAllByRole("link")[0];
    expect(first.textContent).toBe("AAA");
    fireEvent.click(within(change).getByRole("button"));
    expect(change.getAttribute("aria-sort")).toBe("ascending");
  });

  it("says when fundamentals are still loading and labels stale prices", () => {
    render(<ScreenerView screener={{ ...SCREENER, pending_fundamentals: 12, refreshing: true, stale: true }} />);
    expect(screen.getByText(/loading fundamentals for 12 more/)).toBeTruthy();
    expect(screen.getByText(/Data as of/)).toBeTruthy();
  });
});

describe("stock analysis sections", () => {
  const trend = { period: "2026-10-01", strong_buy: 14, buy: 21, hold: 8, sell: 1, strong_sell: 0 };

  it("summarises analyst ratings in words and counts", () => {
    expect(consensusLabel(trend)).toBe("Buy");
    expect(consensusLabel({ ...trend, strong_buy: 0, buy: 0, hold: 0, sell: 0 })).toBeNull();
    render(<AnalystRatings trends={[trend, { ...trend, period: "2026-09-01", hold: 9 }]} />);
    expect(screen.getByText("Buy", { selector: "span.font-semibold" })).toBeTruthy();
    expect(screen.getByText(/44 analysts/)).toBeTruthy();
    expect(screen.getByRole("table")).toBeTruthy();
    expect(screen.getByText(/Not a recommendation/)).toBeTruthy();
  });

  it("shows an empty state without analyst coverage", () => {
    render(<AnalystRatings trends={[]} />);
    expect(screen.getByText("No analyst coverage for this symbol")).toBeTruthy();
  });

  it("marks earnings beats and misses with words and arrows", () => {
    render(
      <EarningsHistory
        currency="USD"
        quarters={[
          { period: "2026-09-30", quarter: 4, year: 2026, eps_actual: null, eps_estimate: "1.60", surprise: null, surprise_pct: null },
          { period: "2026-06-30", quarter: 3, year: 2026, eps_actual: "1.57", eps_estimate: "1.43", surprise: "0.14", surprise_pct: "9.79" },
          { period: "2026-03-31", quarter: 2, year: 2026, eps_actual: "1.20", eps_estimate: "1.30", surprise: "-0.10", surprise_pct: "-7.69" },
        ]}
      />,
    );
    expect(screen.getByText("Beat")).toBeTruthy();
    expect(screen.getByText("Missed")).toBeTruthy();
    expect(screen.getByText("▲")).toBeTruthy();
    expect(screen.getByText("▼")).toBeTruthy();
    expect(screen.getByText("Q4 2026")).toBeTruthy();
  });
});

describe("compare symbols parsing", () => {
  it("upper-cases, de-duplicates, drops invalid entries and caps at four", () => {
    expect(parseSymbols("aapl, msft,AAPL,bad symbol,,nvda,spy,qqq")).toEqual(["AAPL", "MSFT", "NVDA", "SPY"]);
    expect(parseSymbols(null)).toEqual([]);
  });
});

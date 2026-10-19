import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CalendarView, shiftDate } from "@/components/calendar/CalendarView";
import { ForexView, convertAmount, formatRate } from "@/components/forex/ForexView";
import { StockActions } from "@/components/stock/StockActions";
import type { EarningsWeek, ForexBoard, SymbolInfo } from "@/types/api";
import { SESSION, json, mockApi, renderWithAuth } from "./helpers";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
  usePathname: () => "/stock/VOD",
  useSearchParams: () => new URLSearchParams(),
}));

const signedIn = { "POST /api/v1/auth/refresh": json(SESSION) };
const anonymous = { "POST /api/v1/auth/refresh": json({ code: "not_authenticated" }, 401) };

const base: SymbolInfo = {
  symbol: "AAPL",
  display_symbol: "AAPL",
  description: "APPLE INC",
  exchange: "US",
  type: "Common Stock",
  currency: "USD",
  price_available: true,
  streamable: true,
  tradable: true,
  price_note: null,
  trade_note: null,
  quote_delay_min: null,
};
const LSE_NOTE = "Prices for London Stock Exchange listings aren't on our current data plan, so no price or chart will show.";

describe("StockActions explanations", () => {
  it("explains that prices won't show for an unpriced symbol, next to the watchlist option", async () => {
    mockApi({ ...signedIn, "GET /api/v1/watchlists": json([{ id: 1, name: "My watchlist", created_at: "x", symbols: [] }]) });
    renderWithAuth(
      <StockActions
        info={{ ...base, symbol: "VOD", display_symbol: "VOD", exchange: "L", price_available: false, streamable: false, tradable: false, price_note: LSE_NOTE, trade_note: LSE_NOTE }}
        price={null}
        currency="GBP"
      />,
    );
    const note = await screen.findByRole("note");
    expect(note.textContent).toContain("London Stock Exchange");
    expect(note.textContent).toContain("You can still add it to a watchlist");
    expect(await screen.findByLabelText("Add VOD to a watchlist")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Trade (paper)" })).toBeNull();
    expect(screen.queryByText(/No paper trading:/)).toBeNull(); // same reason isn't repeated twice
  });

  it("says why forex can't be paper traded", async () => {
    mockApi({ ...signedIn, "GET /api/v1/watchlists": json([]) });
    renderWithAuth(
      <StockActions
        info={{ ...base, symbol: "OANDA:XAU_USD", display_symbol: "XAU/USD", exchange: "OANDA", type: "Forex", streamable: false, tradable: false, trade_note: "Paper trading covers US-listed stocks and ETFs; forex and metals can be watched but not traded.", quote_delay_min: 5 }}
        price="4150"
        currency="USD"
      />,
    );
    expect((await screen.findByText(/No paper trading:/)).parentElement?.textContent).toContain("can be watched but not traded");
    expect(screen.queryByRole("note")).toBeNull(); // it does have prices
  });

  it("offers trading for US stocks", async () => {
    mockApi({ ...signedIn, "GET /api/v1/watchlists": json([]) });
    renderWithAuth(<StockActions info={base} price="250" currency="USD" />);
    expect(await screen.findByRole("button", { name: "Trade (paper)" })).toBeTruthy();
  });
});

const BOARD: ForexBoard = {
  rows: [
    { pair: "EUR/USD", group: "Majors", symbol: "OANDA:EUR_USD", rate: "1.10", change_pct: "0.40", derived: false },
    { pair: "EUR/INR", group: "Indian rupee", symbol: "FX:EUR_INR", rate: "88.00000000", change_pct: "0.40", derived: true },
    { pair: "XAU/INR", group: "Metals", symbol: null, rate: null, change_pct: null, derived: true },
  ],
  usd_per_unit: { USD: "1", EUR: "1.10", INR: "0.0125", XAU: "4000" },
  currencies: [
    { code: "USD", name: "US dollar" },
    { code: "EUR", name: "Euro" },
    { code: "INR", name: "Indian rupee" },
    { code: "XAU", name: "Gold (troy ounce)" },
    { code: "GBP", name: "British pound" },
  ],
  as_of: "2026-10-19T12:00:00Z",
  stale: false,
  refreshing: false,
  refresh_interval_min: 60,
};

describe("forex helpers", () => {
  it("formats rates by magnitude and converts through USD", () => {
    expect(formatRate("0.00533333")).toBe("0.005333");
    expect(formatRate(88)).toBe("88.0000");
    expect(formatRate(350000)).toBe("350,000.00");
    expect(convertAmount(100, "EUR", "INR", BOARD.usd_per_unit)).toBeCloseTo(8800);
    expect(convertAmount(1, "XAU", "INR", BOARD.usd_per_unit)).toBeCloseTo(320000);
    expect(convertAmount(1, "GBP", "INR", BOARD.usd_per_unit)).toBeNull(); // no GBP rate loaded
  });
});

describe("ForexView", () => {
  it("shows a warming state, then the grouped board with derived markers", async () => {
    let calls = 0;
    mockApi({
      ...anonymous,
      "GET /api/v1/forex": () => {
        calls += 1;
        return json(calls === 1 ? { ...BOARD, as_of: null, refreshing: true } : BOARD);
      },
    });
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      renderWithAuth(<ForexView />);
      expect(await screen.findByText(/Fetching the latest rates/)).toBeTruthy();
      await act(async () => {
        vi.advanceTimersByTime(4100);
      });
      expect(await screen.findByText("Indian rupee")).toBeTruthy();
    } finally {
      vi.useRealTimers();
    }
    expect(screen.getByText("88.0000")).toBeTruthy();
    expect(screen.getAllByText("derived cross rate").length).toBe(2);
    expect(screen.getByRole("link", { name: "EUR/USD" }).getAttribute("href")).toBe("/stock/OANDA%3AEUR_USD");
  });

  it("converts and swaps, using only currencies with a rate", async () => {
    mockApi({ ...anonymous, "GET /api/v1/forex": json(BOARD) });
    renderWithAuth(<ForexView />);
    const converter = (await screen.findByText("Currency converter")).closest("section") as HTMLElement;
    expect(within(converter).queryByText(/GBP: British pound/)).toBeNull();
    fireEvent.change(within(converter).getByLabelText("From"), { target: { value: "EUR" } });
    expect(converter.textContent).toContain("8,800.00 INR"); // 2 decimals at 1,000 and above
    expect(converter.textContent).toContain("1 EUR = 88.0000 INR");
    fireEvent.click(within(converter).getByRole("button", { name: "Swap currencies" }));
    expect(converter.textContent).toContain("1 INR = 0.011364 EUR");
  });

  it("shows a retryable error", async () => {
    mockApi({ ...anonymous, "GET /api/v1/forex": json({ detail: "Server trouble", code: "unknown" }, 500) });
    renderWithAuth(<ForexView />);
    expect((await screen.findByRole("alert")).textContent).toContain("Server trouble");
  });
});

const WEEK: EarningsWeek = {
  week_start: "2026-10-19",
  week_end: "2026-10-25",
  total: 2,
  as_of: "2026-10-19T12:00:00Z",
  stale: false,
  events: [
    { symbol: "AAPL", name: "APPLE INC", date: "2026-10-20", session: "before_open", quarter: 3, year: 2026, eps_estimate: "1.00", eps_actual: "1.10", eps_surprise_pct: "10.0", revenue_estimate: "90000000000", revenue_actual: null, in_watchlist: true },
    { symbol: "MSFT", name: "MICROSOFT", date: "2026-10-22", session: "after_close", quarter: 1, year: 2027, eps_estimate: "3.00", eps_actual: null, eps_surprise_pct: null, revenue_estimate: null, revenue_actual: null, in_watchlist: false },
  ],
};

describe("CalendarView", () => {
  it("lists earnings by day, filters, and offers the watchlist filter to signed-in users", async () => {
    const { calls } = mockApi({ ...signedIn, "GET /api/v1/calendar/earnings": json(WEEK) });
    renderWithAuth(<CalendarView initialTab="earnings" initialWeek="2026-10-21" />);
    expect(await screen.findByText("APPLE INC")).toBeTruthy();
    expect(screen.getByText("Before open")).toBeTruthy();
    expect(screen.getByText("+10.00%")).toBeTruthy();
    expect(screen.getByText("on your watchlist")).toBeTruthy();

    fireEvent.change(screen.getByLabelText("Filter earnings by symbol or company"), { target: { value: "micro" } });
    expect(screen.queryByText("APPLE INC")).toBeNull();
    expect(screen.getByText("MICROSOFT")).toBeTruthy();

    fireEvent.click(screen.getByLabelText("My watchlists only"));
    await waitFor(() => expect(calls.some((c) => c.method === "GET" && c.path === "/api/v1/calendar/earnings" && calls.indexOf(c) > 1)).toBe(true));
  });

  it("asks anonymous users to sign in for the watchlist filter and moves between weeks", async () => {
    const { fetchMock } = mockApi({ ...anonymous, "GET /api/v1/calendar/earnings": json(WEEK) });
    renderWithAuth(<CalendarView initialTab="earnings" initialWeek="2026-10-21" />);
    expect(await screen.findByText(/to filter by your watchlists/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Next week" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).includes("week=2026-10-28"))).toBe(true));
  });

  it("shows the IPO tab with an empty state", async () => {
    mockApi({
      ...anonymous,
      "GET /api/v1/calendar/earnings": json(WEEK),
      "GET /api/v1/calendar/ipos": json({ week_start: "2026-10-19", week_end: "2026-10-25", events: [], as_of: "x", stale: false }),
    });
    renderWithAuth(<CalendarView initialTab="ipos" initialWeek="2026-10-21" />);
    expect(await screen.findByText("No IPOs scheduled this week")).toBeTruthy();
  });

  it("shifts dates in UTC", () => {
    expect(shiftDate("2026-10-26", -7)).toBe("2026-10-19");
    expect(shiftDate("2026-12-29", 7)).toBe("2027-01-05");
  });
});

import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PortfolioView } from "@/components/portfolio/PortfolioView";
import { WatchlistsView } from "@/components/portfolio/WatchlistsView";
import { TradePanel } from "@/components/stock/StockActions";
import { liveTotals, revaluePosition } from "@/lib/portfolio";
import type { Portfolio, Position, SymbolInfo, Watchlist } from "@/types/api";
import { SESSION, json, mockApi, renderWithAuth } from "./helpers";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
  usePathname: () => "/watchlists",
  useSearchParams: () => new URLSearchParams(),
}));

const AAPL: SymbolInfo = {
  symbol: "AAPL",
  display_symbol: "AAPL",
  description: "APPLE INC",
  exchange: "US",
  type: "Common Stock",
  currency: "USD",
  price_available: true,
  streamable: true,
};
const VOD: SymbolInfo = { ...AAPL, symbol: "VOD", display_symbol: "VOD", description: "VODAFONE", exchange: "L", price_available: false, streamable: false };

const quoteEnvelope = (symbol: string, price: string, stale = false) => ({
  data: {
    symbol,
    price,
    change: "1",
    change_pct: "0.5",
    open: null,
    high: null,
    low: null,
    prev_close: "100",
    timestamp: "2026-10-19T14:00:00Z",
    currency: "USD",
  },
  as_of: "2026-10-19T14:00:00Z",
  source: "finnhub",
  stale,
});

const refresh = { "POST /api/v1/auth/refresh": json(SESSION) };

describe("WatchlistsView", () => {
  it("shows a loading state, then rows with prices and plan-limit notes", async () => {
    const list: Watchlist = { id: 1, name: "My watchlist", created_at: "2026-10-19T10:00:00Z", symbols: [AAPL, VOD] };
    mockApi({
      ...refresh,
      "GET /api/v1/watchlists": json([list]),
      "GET /api/v1/quotes": json({
        results: [
          { symbol: "AAPL", quote: quoteEnvelope("AAPL", "250.5", true), error: null },
          { symbol: "VOD", quote: null, error: "unavailable" },
        ],
      }),
    });
    renderWithAuth(<WatchlistsView />);
    expect(screen.getByRole("status", { name: "Loading watchlists" })).toBeTruthy();
    const table = await screen.findByRole("table");
    await waitFor(() => expect(within(table).getByText(/250\.50/)).toBeTruthy());
    expect(within(table).getByText(/Data as of/)).toBeTruthy(); // stale quote is labelled
    expect(within(table).getByText("Not on our data plan")).toBeTruthy();
  });

  it("shows the empty state and surfaces API errors from actions", async () => {
    const list: Watchlist = { id: 1, name: "My watchlist", created_at: "2026-10-19T10:00:00Z", symbols: [] };
    mockApi({
      ...refresh,
      "GET /api/v1/watchlists": json([list]),
      "POST /api/v1/watchlists": json({ detail: "You already have a watchlist with that name.", code: "duplicate_name" }, 409),
    });
    renderWithAuth(<WatchlistsView />);
    expect(await screen.findByText("This watchlist is empty")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "New list" }));
    fireEvent.change(screen.getByLabelText("New list"), { target: { value: "My watchlist" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Create" }));
    });
    expect((await screen.findByRole("alert")).textContent).toContain("already have a watchlist");
  });

  it("asks for confirmation before deleting a list", async () => {
    const list: Watchlist = { id: 7, name: "Tech", created_at: "2026-10-19T10:00:00Z", symbols: [] };
    const { calls } = mockApi({
      ...refresh,
      "GET /api/v1/watchlists": json([list]),
      "DELETE /api/v1/watchlists/7": json(null, 204),
    });
    renderWithAuth(<WatchlistsView />);
    fireEvent.click(await screen.findByRole("button", { name: "Delete list" }));
    const dialog = screen.getByRole("alertdialog");
    expect(within(dialog).getByText(/can't be undone/)).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "Delete list" }));
    await act(async () => {
      fireEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Delete list" }));
    });
    expect(calls.some((c) => c.method === "DELETE" && c.path === "/api/v1/watchlists/7")).toBe(true);
    expect(await screen.findByText("You don't have any watchlists yet")).toBeTruthy();
  });

  it("shows a retryable error when watchlists fail to load", async () => {
    mockApi({ ...refresh, "GET /api/v1/watchlists": json({ detail: "Server trouble", code: "unknown" }, 500) });
    renderWithAuth(<WatchlistsView />);
    expect((await screen.findByRole("alert")).textContent).toContain("Server trouble");
    expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy();
  });
});

const position: Position = {
  symbol: "AAPL",
  display_symbol: "AAPL",
  description: "APPLE INC",
  quantity: "10",
  avg_cost: "100",
  currency: "USD",
  last_price: "110",
  price_as_of: "2026-10-19T14:00:00Z",
  price_stale: false,
  market_value: "1100",
  cost_basis: "1000",
  unrealized_pnl: "100",
  unrealized_pnl_pct: "10",
};
const portfolio: Portfolio = {
  id: 1,
  name: "Paper portfolio",
  base_currency: "USD",
  starting_cash: "100000",
  cash: "99000",
  market_value: "1100",
  equity: "100100",
  total_return: "100",
  total_return_pct: "0.1",
  realized_pnl: "0",
  positions: [position],
  incomplete: false,
  as_of: "2026-10-19T14:00:00Z",
};

describe("live portfolio maths", () => {
  it("revalues with a newer live trade and counts unpriced positions at cost", () => {
    const live = revaluePosition(position, { symbol: "AAPL", price: "120", timestamp: "2026-10-19T15:00:00Z", volume: null });
    expect(live).toMatchObject({ price: 120, marketValue: 1200, unrealizedPnl: 200, live: true });
    expect(revaluePosition(position, { symbol: "AAPL", price: "90", timestamp: "2026-10-19T13:00:00Z", volume: null }).price).toBe(110);

    const unpriced = revaluePosition({ ...position, last_price: null }, undefined);
    expect(liveTotals(portfolio, [unpriced]).equity).toBe(100000);
  });
});

describe("PortfolioView", () => {
  it("renders totals, positions and trade history", async () => {
    mockApi({
      ...refresh,
      "GET /api/v1/portfolio": json(portfolio),
      "GET /api/v1/portfolio/trades": json([
        { id: 1, symbol: "AAPL", display_symbol: "AAPL", side: "buy", quantity: "10", price: "100", currency: "USD", notional: "1000", realized_pnl: null, executed_at: "2026-10-19T13:00:00Z", price_as_of: "2026-10-19T13:00:00Z" },
      ]),
    });
    renderWithAuth(<PortfolioView />);
    expect(await screen.findByText("Total equity")).toBeTruthy();
    expect(screen.getByText(/100,100\.00/)).toBeTruthy();
    const positions = screen.getByRole("table", { name: "Open positions" });
    expect(within(positions).getByText(/1,100\.00/)).toBeTruthy();
    expect(await screen.findByRole("table", { name: /Trade history/ })).toBeTruthy();
  });

  it("shows an empty state with a pointer to trading", async () => {
    mockApi({
      ...refresh,
      "GET /api/v1/portfolio": json({ ...portfolio, positions: [], cash: "100000" }),
      "GET /api/v1/portfolio/trades": json([]),
    });
    renderWithAuth(<PortfolioView />);
    expect(await screen.findByText("No positions yet")).toBeTruthy();
    expect(await screen.findByText("No trades yet")).toBeTruthy();
  });

  it("resets only after confirmation", async () => {
    const { calls } = mockApi({
      ...refresh,
      "GET /api/v1/portfolio": json(portfolio),
      "GET /api/v1/portfolio/trades": json([]),
      "POST /api/v1/portfolio/reset": json({ ...portfolio, positions: [], cash: "100000" }),
    });
    renderWithAuth(<PortfolioView />);
    fireEvent.click(await screen.findByRole("button", { name: "Reset portfolio" }));
    expect(calls.some((c) => c.path === "/api/v1/portfolio/reset")).toBe(false);
    await act(async () => {
      fireEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Reset portfolio" }));
    });
    expect(calls.some((c) => c.path === "/api/v1/portfolio/reset")).toBe(true);
    expect(await screen.findByText("No positions yet")).toBeTruthy();
  });
});

describe("TradePanel", () => {
  const open = async () => {
    renderWithAuth(<TradePanel info={AAPL} price="250" currency="USD" />);
    fireEvent.click(screen.getByRole("button", { name: "Trade (paper)" }));
  };

  it("validates quantity before review", async () => {
    mockApi(refresh);
    await open();
    fireEvent.change(screen.getByLabelText("Quantity (shares)"), { target: { value: "1.1234567" } });
    fireEvent.click(screen.getByRole("button", { name: "Review order" }));
    expect(screen.getByRole("alert").textContent).toContain("up to 6 decimal places");
  });

  it("reviews, confirms and shows the fill", async () => {
    const { calls } = mockApi({
      ...refresh,
      "POST /api/v1/portfolio/orders": json(
        { id: 9, symbol: "AAPL", display_symbol: "AAPL", side: "buy", quantity: "2", price: "250.10", currency: "USD", notional: "500.20", realized_pnl: null, executed_at: "2026-10-19T14:00:00Z", price_as_of: "2026-10-19T14:00:00Z" },
        201,
      ),
    });
    await open();
    fireEvent.change(screen.getByLabelText("Quantity (shares)"), { target: { value: "2" } });
    expect(screen.getByText(/Estimated cost: \$500\.00/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Review order" }));
    expect(screen.getByText(/final price is set when the order fills/)).toBeTruthy();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Confirm buy" }));
    });
    expect((await screen.findByRole("status")).textContent).toMatch(/Bought 2 AAPL at \$250\.10/);
    const body = JSON.parse(String(calls.find((c) => c.path === "/api/v1/portfolio/orders")?.init?.body));
    expect(body).toEqual({ symbol: "AAPL", side: "buy", quantity: "2" }); // quantity stays an exact string
  });

  it("shows business errors from the server", async () => {
    mockApi({
      ...refresh,
      "POST /api/v1/portfolio/orders": json({ detail: "Not enough cash: this order costs 500,000.00 USD", code: "insufficient_cash" }, 422),
    });
    await open();
    fireEvent.change(screen.getByLabelText("Quantity (shares)"), { target: { value: "2000" } });
    fireEvent.click(screen.getByRole("button", { name: "Review order" }));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Confirm buy" }));
    });
    expect((await screen.findByRole("alert")).textContent).toContain("Not enough cash");
  });
});

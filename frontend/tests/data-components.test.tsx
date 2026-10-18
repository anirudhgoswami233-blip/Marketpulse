import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SearchBox } from "@/components/search/SearchBox";
import { PriceChart } from "@/components/stock/PriceChart";
import type { Chart, Envelope } from "@/types/api";

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn(), push: vi.fn() }) }));

// The chart library needs a real canvas; stub it and assert on our own states instead.
const setData = vi.fn();
vi.mock("lightweight-charts", () => ({
  AreaSeries: {},
  createChart: () => ({
    addSeries: () => ({ setData, applyOptions: vi.fn() }),
    timeScale: () => ({ fitContent: vi.fn() }),
    subscribeCrosshairMove: vi.fn(),
    applyOptions: vi.fn(),
    remove: vi.fn(),
  }),
}));

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

describe("SearchBox", () => {
  const type = (value: string) => fireEvent.change(screen.getByRole("combobox"), { target: { value } });

  it("shows loading, then results from our symbol directory", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({
        query: "app",
        results: [
          {
            symbol: "AAPL",
            display_symbol: "AAPL",
            description: "APPLE INC",
            exchange: "US",
            type: "Common Stock",
            currency: "USD",
            price_available: true,
            streamable: true,
          },
        ],
      }),
    );
    render(<SearchBox />);
    type("app");
    expect(screen.getByRole("status").textContent).toContain("Searching");
    expect(await screen.findByRole("option")).toBeTruthy();
    expect(screen.getByRole("option").getAttribute("href")).toBe("/stock/AAPL");
    expect(String(fetchMock.mock.calls[0][0])).toContain("/api/v1/search?q=app");
  });

  it("shows an empty state", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ query: "zzzz", results: [] }));
    render(<SearchBox />);
    type("zzzz");
    expect(await screen.findByText(/No matches/)).toBeTruthy();
  });

  it("shows an error with retry", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("network down")).mockResolvedValue(
      jsonResponse({ query: "app", results: [] }),
    );
    render(<SearchBox />);
    type("app");
    expect((await screen.findByRole("alert")).textContent).toContain("couldn't reach");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText(/No matches/)).toBeTruthy();
  });
});

function chartEnvelope(overrides: Partial<Envelope<Chart>> = {}, bars = 2): Envelope<Chart> {
  return {
    data: {
      symbol: "AAPL",
      range: "1M",
      interval: "1day",
      currency: "USD",
      timezone: "America/New_York",
      bars: Array.from({ length: bars }, (_, i) => ({
        timestamp: `2026-10-1${5 + i}T00:00:00Z`,
        open: "100",
        high: "101",
        low: "99",
        close: String(100 + i),
        volume: 1000,
      })),
    },
    as_of: "2026-10-16T20:00:00Z",
    source: "price_bars",
    stale: false,
    ...overrides,
  };
}

describe("PriceChart", () => {
  it("shows a skeleton, then draws the chart", async () => {
    fetchMock.mockResolvedValue(jsonResponse(chartEnvelope()));
    render(<PriceChart symbol="AAPL" currency="USD" />);
    expect(screen.getByRole("status", { name: "Loading chart" })).toBeTruthy();
    expect(await screen.findByTestId("price-chart")).toBeTruthy();
    expect(setData).toHaveBeenCalled();
    expect(screen.queryByText(/Data as of/)).toBeNull();
  });

  it("labels stale data", async () => {
    fetchMock.mockResolvedValue(jsonResponse(chartEnvelope({ stale: true })));
    render(<PriceChart symbol="AAPL" currency="USD" />);
    expect(await screen.findByText(/Data as of/)).toBeTruthy();
  });

  it("shows an empty state when there are no bars", async () => {
    fetchMock.mockResolvedValue(jsonResponse(chartEnvelope({}, 0)));
    render(<PriceChart symbol="AAPL" currency="USD" />);
    expect(await screen.findByText("No price history for this range")).toBeTruthy();
  });

  it("explains plan limits without offering a pointless retry", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ detail: "not on plan", code: "unavailable", provider: "twelvedata" }, 503),
    );
    render(<PriceChart symbol="AAPL" currency="USD" />);
    expect((await screen.findByRole("alert")).textContent).toContain("isn't available on our current data plan");
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
  });

  it("retries temporary errors and refetches when the range changes", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ detail: "Provider down", code: "provider_error" }, 502))
      .mockResolvedValue(jsonResponse(chartEnvelope()));
    render(<PriceChart symbol="AAPL" currency="USD" />);
    fireEvent.click(await screen.findByRole("button", { name: "Try again" }));
    expect(await screen.findByTestId("price-chart")).toBeTruthy();

    await act(async () => {
      fireEvent.click(screen.getByRole("tab", { name: "1Y" }));
    });
    expect(String(fetchMock.mock.calls.at(-1)?.[0])).toContain("range=1Y");
  });
});

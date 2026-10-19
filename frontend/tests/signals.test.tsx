import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { BriefView } from "@/components/signals/BriefView";
import { DISCLAIMER, SignalBadge, SignalCard } from "@/components/signals/SignalCard";
import type { Brief, BriefStatus, Signal } from "@/types/api";
import { SESSION, json, mockApi, renderWithAuth } from "./helpers";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
  usePathname: () => "/brief",
  useSearchParams: () => new URLSearchParams(),
}));

const SIGNAL: Signal = {
  id: 1,
  symbol: "AAPL",
  display_symbol: "AAPL",
  description: "APPLE INC",
  signal_date: "2026-10-19",
  engine_version: "v1",
  score: 43,
  label: "Bullish signals",
  reasons: [
    { rule: "rsi", direction: 1, weight: 1, reason: "RSI 28 = oversold (below 30)" },
    { rule: "sma200", direction: -1, weight: 1.5, reason: "Price 229.00 below 200-day average (240.00)" },
    { rule: "macd", direction: 0, weight: 1, reason: "No recent MACD crossover (MACD below signal line)" },
  ],
  skipped: [{ rule: "news", reason: "Too few recent headlines to judge tone (1)." }],
  indicators: { rsi14: 28 },
  price_at_signal: "229.00",
  currency: "USD",
  outcomes: [{ horizon_days: 1, outcome_date: "2026-10-20", return_pct: "1.25" }],
  disclaimer: DISCLAIMER,
};

describe("SignalCard", () => {
  it("shows the label with reasons, skipped rules, outcomes and the disclaimer", () => {
    render(<SignalCard signal={SIGNAL} showSymbol />);
    expect(screen.getByText("Bullish signals")).toBeTruthy();
    expect(screen.getByText("RSI 28 = oversold (below 30)")).toBeTruthy();
    expect(screen.getByLabelText("bullish reading")).toBeTruthy();
    expect(screen.getByLabelText("bearish reading")).toBeTruthy();
    expect(screen.getByText(/Too few recent headlines/)).toBeTruthy();
    expect(screen.getByText(/1d \+1\.25%/)).toBeTruthy();
    expect(screen.getByText(DISCLAIMER)).toBeTruthy();
    expect(screen.queryByText(/\b(buy|sell)\b/i)).toBeNull();
  });

  it("explains when there's nothing to read yet", () => {
    render(<SignalCard signal={{ ...SIGNAL, reasons: [], label: "Neutral", score: 0 }} />);
    expect(screen.getByText("Not enough data to read any indicator yet.")).toBeTruthy();
  });

  it("badges never rely on colour alone", () => {
    render(<SignalBadge label="Bearish signals" score={-40} />);
    expect(screen.getByText("▼")).toBeTruthy();
    expect(screen.getByText("Bearish signals")).toBeTruthy();
    expect(screen.getByText("(-40)")).toBeTruthy();
  });
});

const BRIEF: Brief = {
  id: 5,
  brief_date: "2026-10-20",
  generated_at: "2026-10-20T02:00:00Z",
  generator: "template",
  summary_md: "…",
  overnight: {
    regions: [{ region: "Americas", avg_change_pct: 0.8, detail: ["SPY (S&P 500) +0.80%"] }],
    as_of: "2026-10-19T20:05:00Z",
    unavailable: ["VOD"],
  },
  items: [
    { source: "watchlist", signal: SIGNAL },
    { source: "trending", signal: { ...SIGNAL, id: 2, symbol: "NVDA", display_symbol: "NVDA", label: "Bearish signals", score: -35 } },
  ],
  emailed_at: null,
  disclaimer: DISCLAIMER,
};

const status = (overrides: Partial<BriefStatus> = {}): BriefStatus => ({
  brief: null,
  generating: false,
  next_scheduled_at: "2026-10-21T02:00:00Z",
  email_available: false,
  ...overrides,
});

describe("BriefView", () => {
  it("shows the empty state and starts generation on request", async () => {
    let generating = false;
    const { calls } = mockApi({
      "POST /api/v1/auth/refresh": json(SESSION),
      "GET /api/v1/brief": () => json(status({ generating })),
      "GET /api/v1/briefs": json([]),
      "POST /api/v1/brief/generate": () => {
        generating = true;
        return json(null, 202);
      },
    });
    renderWithAuth(<BriefView date={null} />);
    expect(await screen.findByText("No brief yet")).toBeTruthy();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Generate now" }));
    });
    expect(calls.some((c) => c.method === "POST" && c.path === "/api/v1/brief/generate")).toBe(true);
    expect(await screen.findByText(/Building your brief/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Generating…" })).toBeTruthy();
  });

  it("renders the brief grouped by source, with overnight moves and the disclaimer", async () => {
    mockApi({
      "POST /api/v1/auth/refresh": json(SESSION),
      "GET /api/v1/brief": json(status({ brief: BRIEF })),
      "GET /api/v1/briefs": json([{ brief_date: "2026-10-20", generated_at: BRIEF.generated_at, signal_count: 2 }]),
    });
    renderWithAuth(<BriefView date={null} />);
    expect(await screen.findByText("Your watchlist")).toBeTruthy();
    expect(screen.getByText("Trending today")).toBeTruthy();
    expect(screen.getByText("SPY (S&P 500) +0.80%")).toBeTruthy();
    expect(screen.getByText(/couldn't be computed for: VOD/)).toBeTruthy();
    expect(screen.getAllByText(DISCLAIMER).length).toBeGreaterThan(0);
  });

  it("saves brief settings and explains when email isn't available", async () => {
    const { calls } = mockApi({
      "POST /api/v1/auth/refresh": json(SESSION),
      "GET /api/v1/brief": json(status()),
      "GET /api/v1/briefs": json([]),
      "PATCH /api/v1/auth/me": json({ ...SESSION.user, brief_time: "06:15:00", timezone: "Europe/London" }),
    });
    renderWithAuth(<BriefView date={null} />);
    const settings = (await screen.findByText("Brief settings")).closest("section") as HTMLElement;
    expect(within(settings).getByText(/Email isn't set up on this server yet/)).toBeTruthy();
    expect((within(settings).getByRole("checkbox") as HTMLInputElement).disabled).toBe(true);

    fireEvent.change(within(settings).getByLabelText("Time (your timezone)"), { target: { value: "06:15" } });
    fireEvent.change(within(settings).getByLabelText("Timezone"), { target: { value: "Europe/London" } });
    await act(async () => {
      fireEvent.click(within(settings).getByRole("button", { name: "Save settings" }));
    });
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
    await waitFor(() => expect(within(settings).getByRole("status").textContent).toBe("Saved."));
    const body = JSON.parse(String(calls.find((c) => c.method === "PATCH")?.init?.body));
    expect(body).toEqual({ brief_time: "06:15", timezone: "Europe/London", brief_email_enabled: false });
  });

  it("shows a retryable error if the brief can't load", async () => {
    mockApi({
      "POST /api/v1/auth/refresh": json(SESSION),
      "GET /api/v1/brief": json({ detail: "Server trouble", code: "unknown" }, 500),
      "GET /api/v1/briefs": json([]),
    });
    renderWithAuth(<BriefView date={null} />);
    expect((await screen.findByRole("alert")).textContent).toContain("Server trouble");
  });
});

describe("useAuthedQuery", () => {
  it("keeps showing data while reloading the same resource", async () => {
    const { useAuthedQuery } = await import("@/lib/useAuthedQuery");
    let release: () => void = () => {};
    let n = 0;
    mockApi({
      "POST /api/v1/auth/refresh": json(SESSION),
      "GET /api/v1/briefs": () => {
        n += 1;
        if (n === 1) return json([{ brief_date: "2026-10-19", generated_at: "x", signal_count: 1 }]);
        return new Promise<Response>((resolve) => {
          release = () => resolve(json([{ brief_date: "2026-10-20", generated_at: "x", signal_count: 2 }]));
        });
      },
    });
    function Probe() {
      const { state, reload } = useAuthedQuery<{ brief_date: string }[]>("/api/v1/briefs");
      return (
        <div>
          <p data-testid="state">{state.kind === "ready" ? state.data[0].brief_date : state.kind}</p>
          <button type="button" onClick={reload}>
            reload
          </button>
        </div>
      );
    }
    renderWithAuth(<Probe />);
    await waitFor(() => expect(screen.getByTestId("state").textContent).toBe("2026-10-19"));
    fireEvent.click(screen.getByRole("button", { name: "reload" }));
    expect(screen.getByTestId("state").textContent).toBe("2026-10-19"); // no "loading" flash
    await act(async () => release());
    await waitFor(() => expect(screen.getByTestId("state").textContent).toBe("2026-10-20"));
  });
});

describe("BriefTeaser", () => {
  it("tells signed-in users when the brief can't load instead of hiding it", async () => {
    const { BriefTeaser } = await import("@/components/signals/BriefTeaser");
    mockApi({
      "POST /api/v1/auth/refresh": json(SESSION),
      "GET /api/v1/brief": json({ detail: "boom" }, 500),
    });
    renderWithAuth(<BriefTeaser />);
    expect(await screen.findByText(/couldn.t be loaded right now/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Open the brief" }).getAttribute("href")).toBe("/brief");
  });
});

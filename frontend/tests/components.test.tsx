import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MoversTable } from "@/components/markets/MoversTable";
import { heatColor, SectorHeatmap } from "@/components/markets/SectorHeatmap";
import { NewsList } from "@/components/stock/StockDetails";
import { ChangeText } from "@/components/ui/primitives";
import { ErrorState, StaleBadge } from "@/components/ui/status";

const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh, push: vi.fn() }) }));

describe("StaleBadge", () => {
  it("renders nothing for fresh data", () => {
    const { container } = render(<StaleBadge asOf="2026-10-19T14:05:00Z" stale={false} />);
    expect(container.innerHTML).toBe("");
  });

  it("shows 'Data as of' for stale data", () => {
    render(<StaleBadge asOf="2026-10-19T14:05:00Z" stale />);
    expect(screen.getByText(/Data as of/)).toBeTruthy();
    expect(screen.getByText((_, el) => el?.tagName === "TIME")).toBeTruthy();
  });
});

describe("ErrorState", () => {
  it("retries via the provided callback", () => {
    const onRetry = vi.fn();
    render(<ErrorState message="Provider down" onRetry={onRetry} />);
    expect(screen.getByRole("alert").textContent).toContain("Provider down");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("falls back to refreshing the route", () => {
    render(<ErrorState message="Oops" />);
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(refresh).toHaveBeenCalled();
  });

  it("hides retry for errors that won't change", () => {
    render(<ErrorState message="Not on our plan" retryable={false} />);
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("ChangeText", () => {
  it("never relies on color alone", () => {
    render(<ChangeText change="-1.2" changePct="-0.5" />);
    expect(screen.getByText("▼")).toBeTruthy();
    expect(screen.getByText(/0\.50%/).textContent).toMatch(/[-−]/);
  });
});

describe("SectorHeatmap", () => {
  it("shows an empty state before any prices arrive", () => {
    render(<SectorHeatmap sectors={[{ symbol: "XLK", sector: "Technology", price: null, change_pct: null }]} />);
    expect(screen.getByText("Sector data is loading")).toBeTruthy();
  });

  it("labels each tile with a signed change and arrow", () => {
    render(
      <SectorHeatmap
        sectors={[
          { symbol: "XLK", sector: "Technology", price: "250", change_pct: "-3.02" },
          { symbol: "XLF", sector: "Financials", price: "50", change_pct: "0.45" },
        ]}
      />,
    );
    const links = screen.getAllByRole("link");
    expect(links[0].textContent).toContain("Financials"); // sorted best to worst
    expect(links[1].textContent).toMatch(/▼.*3\.02%/);
  });

  it("maps magnitudes onto the diverging scale", () => {
    expect(heatColor(0.1).background).toBe("var(--div-mid)");
    expect(heatColor(4).background).toBe("var(--div-up-4)");
    expect(heatColor(-1.5).background).toBe("var(--div-down-2)");
  });
});

describe("empty states", () => {
  it("MoversTable", () => {
    render(<MoversTable title="Gainers" movers={[]} />);
    expect(screen.getByText("No gainers right now")).toBeTruthy();
  });

  it("NewsList", () => {
    render(<NewsList items={[]} />);
    expect(screen.getByText("No news in the last 7 days")).toBeTruthy();
  });
});

import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MainNav, isActive } from "@/components/layout/MainNav";

let pathname = "/forex";
vi.mock("next/navigation", () => ({ usePathname: () => pathname }));

beforeEach(() => {
  pathname = "/forex";
});

describe("MainNav", () => {
  it("marks the current route, including nested pages", () => {
    expect(isActive("/", "/")).toBe(true);
    expect(isActive("/forex", "/")).toBe(false); // "/" only matches itself
    expect(isActive("/signals", "/signals")).toBe(true);
    expect(isActive("/signalsx", "/signals")).toBe(false);
    expect(isActive("/brief/2026", "/brief")).toBe(true);

    render(<MainNav />);
    const current = screen.getAllByRole("link", { name: "Forex" }).find((a) => a.getAttribute("aria-current") === "page");
    expect(current).toBeTruthy();
  });

  it("opens the phone menu with both groups and closes it with Escape", () => {
    render(<MainNav />);
    const button = screen.getByRole("button", { name: /Menu/ });
    expect(button.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(button);
    expect(button.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByText("Your tools")).toBeTruthy();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(button.getAttribute("aria-expanded")).toBe("false");
  });

  it("closes the phone menu after navigating", () => {
    const { rerender } = render(<MainNav />);
    fireEvent.click(screen.getByRole("button", { name: /Menu/ }));
    expect(screen.getByText("Your tools")).toBeTruthy();
    pathname = "/macro";
    rerender(<MainNav />);
    expect(screen.queryByText("Your tools")).toBeNull();
  });
});

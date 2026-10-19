import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ThemeToggle } from "@/components/layout/ThemeToggle";
import { THEME_STORAGE_KEY, readTheme, resolveTheme, themeInitScript } from "@/lib/theme";

type Listener = () => void;

/** A controllable prefers-color-scheme media query. */
function mockSystemTheme(initialDark: boolean) {
  const listeners = new Set<Listener>();
  const media = {
    matches: initialDark,
    addEventListener: (_: string, l: Listener) => listeners.add(l),
    removeEventListener: (_: string, l: Listener) => listeners.delete(l),
  };
  vi.stubGlobal("matchMedia", vi.fn(() => media));
  return {
    set(dark: boolean) {
      media.matches = dark;
      listeners.forEach((l) => l());
    },
  };
}

function runInitScript() {
  // The same code the inline <head> script runs before first paint.
  new Function(themeInitScript)();
}

beforeEach(() => {
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
});

afterEach(() => {
  document.documentElement.removeAttribute("data-theme");
});

describe("resolveTheme", () => {
  it("prefers an explicit choice, otherwise the system theme", () => {
    expect(resolveTheme("light", true)).toBe("light");
    expect(resolveTheme("dark", false)).toBe("dark");
    expect(resolveTheme(null, true)).toBe("dark");
    expect(resolveTheme(null, false)).toBe("light");
    expect(resolveTheme("bogus", false)).toBe("light");
  });
});

describe("first visit", () => {
  it("leaves the theme to the system preference when nothing is saved", () => {
    mockSystemTheme(true);
    runInitScript();
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
    expect(readTheme()).toBe("dark");
  });

  it("applies a saved choice over the system preference", () => {
    mockSystemTheme(true);
    localStorage.setItem(THEME_STORAGE_KEY, "light");
    runInitScript();
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    expect(readTheme()).toBe("light");
  });
});

describe("ThemeToggle", () => {
  it("follows the system theme until the user chooses, then remembers the choice", () => {
    const system = mockSystemTheme(false);
    render(<ThemeToggle />);
    expect(screen.getByRole("button", { name: "Switch to dark mode" })).toBeTruthy();

    // OS switches to dark: we follow it while there's no explicit choice.
    act(() => system.set(true));
    expect(screen.getByRole("button", { name: "Switch to light mode" })).toBeTruthy();

    fireEvent.click(screen.getByRole("button"));
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");

    // After choosing, OS changes no longer override the user.
    act(() => system.set(false));
    act(() => system.set(true));
    expect(screen.getByRole("button", { name: "Switch to dark mode" })).toBeTruthy();
  });
});

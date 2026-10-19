"use client";

import { useSyncExternalStore } from "react";

import { readTheme, setTheme, subscribeTheme, type Theme } from "@/lib/theme";

export function ThemeToggle() {
  // The server can't know the system theme; render the light-mode icon until hydrated, then the real one.
  const theme = useSyncExternalStore<Theme>(subscribeTheme, readTheme, () => "light");
  const next: Theme = theme === "dark" ? "light" : "dark";

  return (
    <button
      type="button"
      onClick={() => setTheme(next)}
      aria-label={`Switch to ${next} mode`}
      className="rounded-md border border-border px-2.5 py-1.5 text-sm text-secondary hover:text-primary"
    >
      <span aria-hidden>{theme === "dark" ? "☀" : "☾"}</span>
    </button>
  );
}

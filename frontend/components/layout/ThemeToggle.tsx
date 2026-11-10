"use client";

import { useSyncExternalStore } from "react";

import { readTheme, setTheme, subscribeTheme, type Theme } from "@/lib/theme";

const ICON = { width: 14, height: 14, viewBox: "0 0 16 16", fill: "none", stroke: "currentColor", strokeWidth: 1.5, strokeLinecap: "round" } as const;

export function ThemeToggle() {
  // The server can't know the system theme; render the light-mode icon until hydrated, then the real one.
  const theme = useSyncExternalStore<Theme>(subscribeTheme, readTheme, () => "light");
  const next: Theme = theme === "dark" ? "light" : "dark";

  return (
    <button type="button" onClick={() => setTheme(next)} aria-label={`Switch to ${next} mode`} className="btn btn-md h-7 w-7 px-0">
      {theme === "dark" ? (
        <svg {...ICON} aria-hidden>
          <circle cx="8" cy="8" r="3" />
          <path d="M8 1.5v1.5M8 13v1.5M1.5 8H3M13 8h1.5M3.4 3.4l1.1 1.1M11.5 11.5l1.1 1.1M3.4 12.6l1.1-1.1M11.5 4.5l1.1-1.1" />
        </svg>
      ) : (
        <svg {...ICON} aria-hidden>
          <path d="M13.5 9.5A6 6 0 0 1 6.5 2.5a6 6 0 1 0 7 7Z" strokeLinejoin="round" />
        </svg>
      )}
    </button>
  );
}

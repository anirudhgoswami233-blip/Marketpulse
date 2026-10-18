"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";

import { api, toApiError } from "@/lib/api";
import type { SymbolInfo } from "@/types/api";

const DEBOUNCE_MS = 250;

type Result = { kind: "results"; results: SymbolInfo[] } | { kind: "error"; message: string };
type State = { kind: "idle" } | { kind: "loading" } | Result;

/** Header search: queries our symbol directory (never the data provider) as you type. */
export function SearchBox({ autoFocus = false }: { autoFocus?: boolean }) {
  const router = useRouter();
  const listId = useId();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [retryToken, setRetryToken] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);

  // Results are tagged with the query they answer, so typing shows "Searching…" without extra state.
  const q = query.trim();
  const requestKey = `${q}|${retryToken}`;
  const [result, setResult] = useState<{ key: string; value: Result } | null>(null);
  const state: State = !q ? { kind: "idle" } : result?.key === requestKey ? result.value : { kind: "loading" };

  useEffect(() => {
    if (!q) return;
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      try {
        const data = await api.search(q, 8, { signal: controller.signal });
        setResult({ key: requestKey, value: { kind: "results", results: data.results } });
        setActive(-1);
      } catch (error) {
        if (controller.signal.aborted) return;
        setResult({ key: requestKey, value: { kind: "error", message: toApiError(error).message } });
      }
    }, DEBOUNCE_MS);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [q, requestKey]);

  useEffect(() => {
    const onClick = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  const results = state.kind === "results" ? state.results : [];

  const go = (symbol: SymbolInfo) => {
    setOpen(false);
    setQuery("");
    router.push(`/stock/${encodeURIComponent(symbol.symbol)}`);
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setOpen(true);
      setActive((i) => Math.min(i + 1, results.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((i) => Math.max(i - 1, -1));
    } else if (event.key === "Enter") {
      event.preventDefault();
      if (active >= 0 && results[active]) go(results[active]);
      else if (query.trim()) {
        setOpen(false);
        router.push(`/search?q=${encodeURIComponent(query.trim())}`);
      }
    } else if (event.key === "Escape") {
      setOpen(false);
    }
  };

  return (
    <div ref={containerRef} className="relative w-full max-w-md">
      <input
        type="search"
        role="combobox"
        aria-expanded={open && query.trim().length > 0}
        aria-controls={listId}
        aria-activedescendant={active >= 0 ? `${listId}-${active}` : undefined}
        aria-label="Search stocks, ETFs and forex pairs"
        placeholder="Search symbol or company…"
        autoFocus={autoFocus}
        value={query}
        onChange={(event) => {
          setQuery(event.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={onKeyDown}
        className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-primary placeholder:text-muted focus:border-accent focus:outline-none"
      />
      {open && query.trim() && (
        <div
          id={listId}
          role="listbox"
          className="absolute z-20 mt-1 w-full overflow-hidden rounded-lg border border-border bg-surface shadow-lg"
        >
          {state.kind === "loading" && (
            <div role="status" className="px-3 py-3 text-sm text-secondary">
              Searching…
            </div>
          )}
          {state.kind === "error" && (
            <div role="alert" className="flex items-center justify-between gap-2 px-3 py-3 text-sm">
              <span className="text-primary">{state.message}</span>
              <button
                type="button"
                className="text-xs font-medium text-accent"
                onClick={() => setRetryToken((n) => n + 1)}
              >
                Try again
              </button>
            </div>
          )}
          {state.kind === "results" && results.length === 0 && (
            <div className="px-3 py-3 text-sm text-secondary">No matches for “{query.trim()}”.</div>
          )}
          {results.map((item, index) => (
            <Link
              key={`${item.symbol}-${item.exchange}`}
              id={`${listId}-${index}`}
              role="option"
              aria-selected={index === active}
              href={`/stock/${encodeURIComponent(item.symbol)}`}
              onClick={() => {
                setOpen(false);
                setQuery("");
              }}
              className={`flex items-center justify-between gap-3 px-3 py-2 text-sm ${
                index === active ? "bg-surface-2" : "hover:bg-surface-2"
              }`}
            >
              <span className="min-w-0">
                <span className="font-semibold text-primary">{item.display_symbol}</span>{" "}
                <span className="truncate text-secondary">{item.description}</span>
              </span>
              <span className="shrink-0 text-xs text-muted">
                {item.exchange} · {item.type || "—"}
              </span>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

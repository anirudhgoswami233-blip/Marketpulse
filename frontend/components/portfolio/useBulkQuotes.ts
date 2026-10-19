"use client";

import { useCallback, useEffect, useState } from "react";

import { api, toApiError, type ApiError } from "@/lib/api";
import type { QuoteResult } from "@/types/api";

export type BulkQuotesState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ready"; bySymbol: Record<string, QuoteResult> }
  | { kind: "error"; error: ApiError };

/** Snapshot quotes for a set of symbols (served from the backend's 60s cache); live ticks come via SSE. */
export function useBulkQuotes(symbols: string[]) {
  const key = [...new Set(symbols)].sort().join(",");
  const [version, setVersion] = useState(0);
  const requestKey = key ? `${key}#${version}` : "";
  const [result, setResult] = useState<{ key: string; state: BulkQuotesState } | null>(null);

  useEffect(() => {
    if (!key) return;
    const controller = new AbortController();
    api
      .quotes(key.split(","), { signal: controller.signal })
      .then((data) => {
        const bySymbol = Object.fromEntries(data.results.map((r) => [r.symbol, r]));
        setResult({ key: requestKey, state: { kind: "ready", bySymbol } });
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setResult({ key: requestKey, state: { kind: "error", error: toApiError(error) } });
        }
      });
    return () => controller.abort();
  }, [key, requestKey]);

  const state: BulkQuotesState = !key
    ? { kind: "idle" }
    : result?.key === requestKey
      ? result.state
      : { kind: "loading" };
  const reload = useCallback(() => setVersion((v) => v + 1), []);
  return { state, reload };
}

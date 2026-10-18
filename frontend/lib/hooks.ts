"use client";

import { useEffect, useState, useSyncExternalStore } from "react";

import { streamUrl } from "@/lib/api";
import type { LiveTrade, StreamReady } from "@/types/api";

const noopSubscribe = () => () => {};

/**
 * False during server rendering and hydration, true afterwards. Lets components render
 * viewer-specific values (local time zone) without a hydration mismatch.
 */
export function useHydrated(): boolean {
  return useSyncExternalStore(
    noopSubscribe,
    () => true,
    () => false,
  );
}

/** Re-renders every `intervalMs` with the current time (for clocks and countdowns). */
export function useNow(intervalMs = 30_000): number | null {
  const [now, setNow] = useState<number | null>(null);
  useEffect(() => {
    const tick = () => setNow(Date.now());
    tick();
    const id = window.setInterval(tick, intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs]);
  return now;
}

export type StreamStatus = "connecting" | "live" | "unavailable" | "error";

export interface LiveQuotes {
  trades: Record<string, LiveTrade>;
  status: StreamStatus;
  liveSymbols: string[];
}

/**
 * Subscribes to our backend's SSE price stream (never Finnhub directly). The backend throttles to one
 * update per symbol per second; EventSource reconnects on its own after network drops.
 */
export function useLiveQuotes(symbols: string[]): LiveQuotes {
  const key = [...new Set(symbols)].sort().join(",");
  const [state, setState] = useState<LiveQuotes>({ trades: {}, status: "connecting", liveSymbols: [] });

  useEffect(() => {
    if (!key || typeof EventSource === "undefined") return;
    const source = new EventSource(streamUrl(key.split(",")));

    source.addEventListener("ready", (event) => {
      const ready = JSON.parse((event as MessageEvent<string>).data) as StreamReady;
      setState((prev) => ({
        ...prev,
        liveSymbols: ready.live,
        status: ready.streaming_enabled && ready.live.length > 0 ? "live" : "unavailable",
      }));
    });
    source.addEventListener("price", (event) => {
      const trade = JSON.parse((event as MessageEvent<string>).data) as LiveTrade;
      setState((prev) => ({ ...prev, trades: { ...prev.trades, [trade.symbol]: trade } }));
    });
    source.onerror = () => {
      setState((prev) => ({ ...prev, status: source.readyState === EventSource.CLOSED ? "error" : "connecting" }));
    };
    return () => source.close();
  }, [key]);

  return state;
}

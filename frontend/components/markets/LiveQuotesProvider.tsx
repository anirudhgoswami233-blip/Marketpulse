"use client";

import { createContext, useContext, type ReactNode } from "react";

import { useLiveQuotes, type LiveQuotes } from "@/lib/hooks";

const LiveQuotesContext = createContext<LiveQuotes | null>(null);

/**
 * One SSE connection for every live price on the page. Browsers cap HTTP/1.1 connections per host at
 * six, so per-widget streams would starve regular API requests.
 */
export function LiveQuotesProvider({ symbols, children }: { symbols: string[]; children: ReactNode }) {
  const live = useLiveQuotes(symbols);
  return <LiveQuotesContext.Provider value={live}>{children}</LiveQuotesContext.Provider>;
}

export function useSharedLiveQuotes(): LiveQuotes {
  const value = useContext(LiveQuotesContext);
  if (!value) throw new Error("useSharedLiveQuotes must be used inside <LiveQuotesProvider>");
  return value;
}

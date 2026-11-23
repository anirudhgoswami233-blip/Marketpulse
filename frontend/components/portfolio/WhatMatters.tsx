"use client";

import { useEffect } from "react";

import { Card, EmptyState, SkeletonBlock } from "@/components/ui/primitives";
import { ErrorState, StaleBadge } from "@/components/ui/status";
import { useAuthedQuery } from "@/lib/useAuthedQuery";
import type { WatchlistNews } from "@/types/api";

/**
 * "What matters": material news across the user's watched symbols. Descriptive labels only, not advice.
 * The backend serves a cached digest and fills it in on a background refresh, so we poll while refreshing.
 */
export function WhatMatters() {
  const { state, reload } = useAuthedQuery<WatchlistNews>("/api/v1/watchlist-news");
  const refreshing = state.kind === "ready" && state.data.refreshing;

  useEffect(() => {
    if (!refreshing) return;
    const timer = setTimeout(reload, 4000);
    return () => clearTimeout(timer);
  }, [refreshing, reload]);

  if (state.kind === "loading") return <SkeletonBlock lines={4} label="Loading news digest" />;
  if (state.kind === "error") {
    return <ErrorState message={state.error.message} retryable={state.error.retryable} onRetry={reload} />;
  }

  const digest = state.data;
  return (
    <Card title="What matters">
      {digest.items.length === 0 ? (
        <EmptyState
          title={
            digest.refreshing
              ? "Scanning your watchlists for material news…"
              : "No market-moving news across your watchlists right now"
          }
        />
      ) : (
        <ul className="divide-y divide-border">
          {digest.items.map((h) => (
            <li key={`${h.symbol}-${h.url}`} className="py-2 first:pt-0 last:pb-0">
              <a href={h.url} target="_blank" rel="noopener noreferrer" className="group block">
                <p className="text-[13px] font-medium text-primary group-hover:text-accent">{h.headline}</p>
                <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-2xs text-muted">
                  <span className="badge">{h.display_symbol}</span>
                  <span className="badge">
                    {h.category_label}
                    {h.materiality === "high" && <span className="uppercase tracking-wide"> · High impact</span>}
                  </span>
                  <span className="tabular">{h.name}</span>
                </div>
              </a>
            </li>
          ))}
        </ul>
      )}
      <div className="mt-2 flex flex-wrap items-center gap-x-2 text-2xs text-muted">
        <StaleBadge asOf={digest.as_of} stale={digest.stale} />
        {digest.refreshing && (
          <span role="status">
            Updating…{digest.symbols_pending > 0 ? ` ${digest.symbols_pending} symbols left` : ""}
          </span>
        )}
      </div>
    </Card>
  );
}

"use client";

import Link from "next/link";

import { useSharedLiveQuotes } from "@/components/markets/LiveQuotesProvider";
import { ChangeText, Skeleton } from "@/components/ui/primitives";
import { formatPrice } from "@/lib/format";
import { mergeLiveTrade } from "@/lib/quotes";
import type { IndexCard } from "@/types/api";

/** Region index proxies (US-listed ETFs) with live prices layered on the snapshot quote. */
export function IndexGrid({ indices }: { indices: IndexCard[] }) {
  const { trades } = useSharedLiveQuotes();
  return (
    <ul className="grid grid-cols-2 gap-2 sm:grid-cols-3">
      {indices.map((index) => {
        const display = mergeLiveTrade(index.quote, trades[index.symbol]);
        return (
          <li key={index.symbol}>
            <Link
              href={`/stock/${encodeURIComponent(index.symbol)}`}
              className="block rounded-lg border border-border px-3 py-2 hover:bg-surface-2"
              title={`${index.symbol} is a US-listed ETF tracking ${index.tracks}; it trades during US market hours.`}
            >
              <div className="flex items-baseline justify-between gap-2">
                <span className="truncate text-sm font-medium text-primary">{index.name}</span>
                <span className="shrink-0 text-xs text-muted">{index.symbol}</span>
              </div>
              {display ? (
                <div className="mt-1 flex items-baseline justify-between gap-2 text-sm">
                  <span className="tabular text-primary">
                    {formatPrice(display.price, index.quote?.currency ?? "USD")}
                    {display.live && (
                      <span className="ml-1 text-xs text-up" aria-label="live">
                        ●
                      </span>
                    )}
                  </span>
                  <ChangeText changePct={display.changePct} className="text-xs" />
                </div>
              ) : (
                <div className="mt-2 flex justify-between" role="status" aria-label={`Loading ${index.name}`}>
                  <Skeleton className="h-4 w-20" />
                  <Skeleton className="h-4 w-14" />
                </div>
              )}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

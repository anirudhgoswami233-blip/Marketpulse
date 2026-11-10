"use client";

import Link from "next/link";

import { useSharedLiveQuotes } from "@/components/markets/LiveQuotesProvider";
import { PriceTick } from "@/components/ui/PriceTick";
import { ChangeText, Skeleton } from "@/components/ui/primitives";
import { formatPrice } from "@/lib/format";
import { mergeLiveTrade } from "@/lib/quotes";
import type { IndexCard } from "@/types/api";

/** Region index proxies (US-listed ETFs) with live prices layered on the snapshot quote. */
export function IndexGrid({ indices, region }: { indices: IndexCard[]; region?: string }) {
  const { trades } = useSharedLiveQuotes();
  return (
    <table className="data-table">
      <caption className="sr-only">{region ? `${region} index proxies` : "Index proxies"}</caption>
      <thead>
        <tr>
          <th scope="col">Index (ETF)</th>
          <th scope="col" className="num">
            Price
          </th>
          <th scope="col" className="num">
            Change
          </th>
        </tr>
      </thead>
      <tbody>
        {indices.map((index) => {
          const display = mergeLiveTrade(index.quote, trades[index.symbol]);
          return (
            <tr key={index.symbol}>
              <td className="max-w-0 w-full truncate">
                <Link
                  href={`/stock/${encodeURIComponent(index.symbol)}`}
                  className="font-medium text-primary hover:text-accent"
                  title={`${index.symbol} is a US-listed ETF tracking ${index.tracks}; it trades during US market hours.`}
                >
                  {index.name}
                </Link>{" "}
                <span className="text-2xs text-muted">{index.symbol}</span>
              </td>
              {display ? (
                <>
                  <td className="num text-primary">
                    {display.live && (
                      <span className="mr-1 text-[0.6em] text-up" role="img" aria-label="live">
                        ●
                      </span>
                    )}
                    <PriceTick value={display.price}>{formatPrice(display.price, index.quote?.currency ?? "USD")}</PriceTick>
                  </td>
                  <td className="num">
                    <ChangeText changePct={display.changePct} />
                  </td>
                </>
              ) : (
                <td colSpan={2} role="status" aria-label={`Loading ${index.name}`}>
                  <Skeleton className="ml-auto h-3.5 w-28" />
                </td>
              )}
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

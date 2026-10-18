"use client";

import { ChangeText } from "@/components/ui/primitives";
import { LocalTime, StaleBadge } from "@/components/ui/status";
import { formatPrice } from "@/lib/format";
import { useLiveQuotes } from "@/lib/hooks";
import { mergeLiveTrade } from "@/lib/quotes";
import type { Envelope, Quote, SymbolInfo } from "@/types/api";

export function LiveQuote({ info, quote }: { info: SymbolInfo; quote: Envelope<Quote> }) {
  const { trades } = useLiveQuotes(info.streamable ? [info.symbol] : []);
  const display = mergeLiveTrade(quote.data, trades[info.symbol]);
  if (!display) return null;
  const currency = quote.data.currency ?? info.currency;

  return (
    <div>
      <div className="flex flex-wrap items-baseline gap-3">
        <span className="tabular text-3xl font-semibold text-primary">{formatPrice(display.price, currency)}</span>
        <ChangeText change={display.change} changePct={display.changePct} className="text-base" />
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted">
        {display.live && (
          <span className="inline-flex items-center gap-1 text-up">
            <span aria-hidden>●</span> Live
          </span>
        )}
        {display.timestamp && (
          <span>
            Last trade <LocalTime iso={display.timestamp} withDate />
          </span>
        )}
        <StaleBadge asOf={quote.as_of} stale={quote.stale} />
      </div>
    </div>
  );
}

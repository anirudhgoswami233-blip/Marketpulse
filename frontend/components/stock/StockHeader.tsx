"use client";

import { StockActions } from "@/components/stock/StockActions";
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
        {info.quote_delay_min !== null ? (
          <span title="No live stream for forex and metals on our data plan">
            Delayed up to {info.quote_delay_min} min · updated <LocalTime iso={quote.as_of} />
          </span>
        ) : (
          display.timestamp && (
            <span>
              Last trade <LocalTime iso={display.timestamp} withDate />
            </span>
          )
        )}
        <StaleBadge asOf={quote.as_of} stale={quote.stale} />
      </div>
      <div className="mt-3">
        <StockActions info={info} price={display.price} currency={currency} />
      </div>
    </div>
  );
}

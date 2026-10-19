"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, type FormEvent } from "react";

import { toApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatMoney, formatNumber, formatPrice } from "@/lib/format";
import { useAuthedQuery } from "@/lib/useAuthedQuery";
import type { OrderSide, SymbolInfo, Trade, Watchlist } from "@/types/api";

const QUANTITY_PATTERN = /^\d+(\.\d{1,6})?$/;

/** "Add to watchlist" and the paper-trading panel for a stock page. */
export function StockActions({ info, price, currency }: { info: SymbolInfo; price: string | null; currency: string | null }) {
  const { status } = useAuth();
  const pathname = usePathname();
  if (status === "loading") return null;
  if (status === "anonymous") {
    return (
      <p className="text-xs text-secondary">
        <Link href={`/login?next=${encodeURIComponent(pathname ?? "/")}`} className="text-accent hover:underline">
          Sign in
        </Link>{" "}
        to add {info.display_symbol} to a watchlist{info.tradable ? " or practise trading it" : ""}.
      </p>
    );
  }
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-start gap-3">
        <AddToWatchlist info={info} />
        {info.tradable ? (
          <TradePanel info={info} price={price} currency={currency ?? info.currency ?? "USD"} />
        ) : (
          info.trade_note &&
          info.trade_note !== info.price_note && (
            <p className="max-w-sm rounded-md bg-surface-2 px-3 py-1.5 text-xs text-secondary">
              <span className="font-medium text-primary">No paper trading: </span>
              {info.trade_note}
            </p>
          )
        )}
      </div>
      {info.price_note && <NoPriceNote note={info.price_note} />}
    </div>
  );
}

/** Shown wherever actions are offered for a symbol we can't price, so the empty price isn't a surprise. */
export function NoPriceNote({ note }: { note: string }) {
  return (
    <p className="flex max-w-xl gap-2 rounded-md bg-surface-2 px-3 py-2 text-xs text-secondary" role="note">
      <span aria-hidden>ⓘ</span>
      <span>
        {note} You can still add it to a watchlist to keep it in view; its row will say the price isn&apos;t
        available.
      </span>
    </p>
  );
}

function AddToWatchlist({ info }: { info: SymbolInfo }) {
  const { authRequest } = useAuth();
  const { state, mutate } = useAuthedQuery<Watchlist[]>("/api/v1/watchlists");
  const [message, setMessage] = useState<{ tone: "ok" | "error"; text: string } | null>(null);

  if (state.kind !== "ready") return null;
  const lists = state.data;
  if (lists.length === 0) {
    return (
      <Link href="/watchlists" className="rounded-md border border-border px-3 py-1.5 text-xs text-secondary hover:text-primary">
        Create a watchlist
      </Link>
    );
  }

  const add = async (watchlist: Watchlist) => {
    setMessage(null);
    try {
      const updated = await authRequest<Watchlist>(`/api/v1/watchlists/${watchlist.id}/items`, {
        method: "POST",
        json: { symbol: info.symbol },
      });
      mutate(lists.map((w) => (w.id === updated.id ? updated : w)));
      setMessage({ tone: "ok", text: `Added to ${watchlist.name}.` });
    } catch (error) {
      setMessage({ tone: "error", text: toApiError(error).message });
    }
  };

  return (
    <div className="space-y-1">
      <label className="flex items-center gap-2 text-xs text-secondary">
        <span>Add to</span>
        <select
          aria-label={`Add ${info.display_symbol} to a watchlist`}
          value=""
          onChange={(event) => {
            const target = lists.find((w) => String(w.id) === event.target.value);
            if (target) void add(target);
          }}
          className="rounded-md border border-border bg-surface px-2 py-1 text-xs text-primary"
        >
          <option value="" disabled>
            Choose a watchlist…
          </option>
          {lists.map((w) => {
            const has = w.symbols.some((s) => s.symbol === info.symbol);
            return (
              <option key={w.id} value={w.id} disabled={has}>
                {w.name}
                {has ? " ✓" : ""}
              </option>
            );
          })}
        </select>
      </label>
      {message && (
        <p role={message.tone === "error" ? "alert" : "status"} className={`text-xs ${message.tone === "ok" ? "text-up" : "text-down"}`}>
          {message.text}
        </p>
      )}
    </div>
  );
}

type Step = { kind: "edit" } | { kind: "review" } | { kind: "submitting" } | { kind: "filled"; trade: Trade };

export function TradePanel({ info, price, currency }: { info: SymbolInfo; price: string | null; currency: string }) {
  const { authRequest } = useAuth();
  const [open, setOpen] = useState(false);
  const [side, setSide] = useState<OrderSide>("buy");
  const [quantity, setQuantity] = useState("");
  const [step, setStep] = useState<Step>({ kind: "edit" });
  const [error, setError] = useState<string | null>(null);

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-surface hover:opacity-90"
      >
        Trade (paper)
      </button>
    );
  }

  const valid = QUANTITY_PATTERN.test(quantity) && Number(quantity) > 0;
  const estimate = valid && price ? Number(quantity) * Number(price) : null;

  const review = (event: FormEvent) => {
    event.preventDefault();
    if (!valid) {
      setError("Enter a quantity greater than zero (up to 6 decimal places).");
      return;
    }
    setError(null);
    setStep({ kind: "review" });
  };

  const submit = async () => {
    setStep({ kind: "submitting" });
    try {
      const trade = await authRequest<Trade>("/api/v1/portfolio/orders", {
        method: "POST",
        json: { symbol: info.symbol, side, quantity },
      });
      setStep({ kind: "filled", trade });
      setQuantity("");
    } catch (err) {
      setError(toApiError(err).message);
      setStep({ kind: "edit" });
    }
  };

  return (
    <section aria-label={`Paper trade ${info.display_symbol}`} className="w-full max-w-sm rounded-xl border border-border bg-surface p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-primary">Paper trade {info.display_symbol}</h2>
        <button type="button" onClick={() => setOpen(false)} className="text-xs text-muted hover:text-primary">
          Close
        </button>
      </div>

      {step.kind === "filled" ? (
        <div role="status" className="space-y-2 text-sm">
          <p className="text-primary">
            {step.trade.side === "buy" ? "Bought" : "Sold"} {formatNumber(step.trade.quantity, 6)} {step.trade.display_symbol} at{" "}
            {formatPrice(step.trade.price, step.trade.currency)} ({formatMoney(step.trade.notional, step.trade.currency)}).
          </p>
          <div className="flex gap-3 text-xs">
            <Link href="/portfolio" className="text-accent hover:underline">
              View portfolio
            </Link>
            <button type="button" onClick={() => setStep({ kind: "edit" })} className="text-secondary hover:text-primary">
              Place another order
            </button>
          </div>
        </div>
      ) : step.kind === "edit" ? (
        <form onSubmit={review} className="space-y-3" noValidate>
          <div role="radiogroup" aria-label="Order side" className="grid grid-cols-2 gap-1 rounded-lg bg-surface-2 p-1">
            {(["buy", "sell"] as const).map((s) => (
              <button
                key={s}
                type="button"
                role="radio"
                aria-checked={side === s}
                onClick={() => setSide(s)}
                className={`rounded-md py-1 text-xs font-medium capitalize ${side === s ? "bg-surface text-primary shadow" : "text-secondary"}`}
              >
                {s}
              </button>
            ))}
          </div>
          <label className="block space-y-1 text-xs">
            <span className="text-secondary">Quantity (shares)</span>
            <input
              inputMode="decimal"
              autoComplete="off"
              value={quantity}
              onChange={(event) => setQuantity(event.target.value.trim())}
              className="tabular w-full rounded-md border border-border bg-surface px-2 py-1.5 text-sm text-primary focus:border-accent focus:outline-none"
            />
          </label>
          <p className="text-xs text-muted">
            {estimate !== null ? <>Estimated {side === "buy" ? "cost" : "proceeds"}: {formatMoney(estimate, currency)}</> : "Market order at the current price."}
          </p>
          {error && (
            <p role="alert" className="text-xs text-down">
              {error}
            </p>
          )}
          <button type="submit" className="w-full rounded-md bg-accent py-1.5 text-xs font-medium text-surface hover:opacity-90">
            Review order
          </button>
        </form>
      ) : (
        <div className="space-y-3 text-sm">
          <p className="text-primary">
            {side === "buy" ? "Buy" : "Sell"} {formatNumber(quantity, 6)} {info.display_symbol}
            {estimate !== null && <> for about {formatMoney(estimate, currency)}</>}.
          </p>
          <p className="text-xs text-muted">The final price is set when the order fills. Virtual money only.</p>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setStep({ kind: "edit" })}
              disabled={step.kind === "submitting"}
              className="flex-1 rounded-md border border-border py-1.5 text-xs text-primary hover:bg-surface-2"
            >
              Back
            </button>
            <button
              type="button"
              onClick={submit}
              disabled={step.kind === "submitting"}
              className="flex-1 rounded-md bg-accent py-1.5 text-xs font-medium text-surface hover:opacity-90 disabled:opacity-60"
            >
              {step.kind === "submitting" ? "Placing…" : `Confirm ${side}`}
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

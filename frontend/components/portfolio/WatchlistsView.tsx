"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";

import { useBulkQuotes } from "@/components/portfolio/useBulkQuotes";
import { LiveQuotesProvider, useSharedLiveQuotes } from "@/components/markets/LiveQuotesProvider";
import { SearchBox } from "@/components/search/SearchBox";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { PriceTick } from "@/components/ui/PriceTick";
import { Card, ChangeText, EmptyState, Skeleton, SkeletonBlock } from "@/components/ui/primitives";
import { ErrorState, StaleBadge } from "@/components/ui/status";
import { toApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatPrice } from "@/lib/format";
import { mergeLiveTrade } from "@/lib/quotes";
import { useAuthedQuery } from "@/lib/useAuthedQuery";
import type { QuoteResult, SymbolInfo, Watchlist } from "@/types/api";

const QUOTE_ERROR_TEXT: Record<NonNullable<QuoteResult["error"]>, string> = {
  unavailable: "No price data",
  not_found: "Unknown symbol",
  provider_error: "Price temporarily unavailable",
};

export function WatchlistsView() {
  const { authRequest } = useAuth();
  const { state, reload, mutate } = useAuthedQuery<Watchlist[]>("/api/v1/watchlists");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [busy, setBusy] = useState(false);

  if (state.kind === "loading") return <SkeletonBlock lines={8} label="Loading watchlists" />;
  if (state.kind === "error") {
    return <ErrorState message={state.error.message} retryable={state.error.retryable} onRetry={reload} />;
  }

  const lists = state.data;
  const selected = lists.find((w) => w.id === selectedId) ?? lists[0] ?? null;
  const replace = (updated: Watchlist) => mutate(lists.map((w) => (w.id === updated.id ? updated : w)));

  const run = async (action: () => Promise<void>) => {
    setActionError(null);
    setBusy(true);
    try {
      await action();
    } catch (error) {
      setActionError(toApiError(error).message);
    } finally {
      setBusy(false);
    }
  };

  const createList = (name: string) =>
    run(async () => {
      const created = await authRequest<Watchlist>("/api/v1/watchlists", { method: "POST", json: { name } });
      mutate([...lists, created]);
      setSelectedId(created.id);
    });

  const renameList = (name: string) =>
    run(async () => {
      if (!selected) return;
      replace(await authRequest<Watchlist>(`/api/v1/watchlists/${selected.id}`, { method: "PATCH", json: { name } }));
    });

  const deleteList = () =>
    run(async () => {
      if (!selected) return;
      await authRequest<void>(`/api/v1/watchlists/${selected.id}`, { method: "DELETE" });
      mutate(lists.filter((w) => w.id !== selected.id));
      setSelectedId(null);
      setConfirmDelete(false);
    });

  const addSymbol = (symbol: SymbolInfo) =>
    run(async () => {
      if (!selected) return;
      replace(
        await authRequest<Watchlist>(`/api/v1/watchlists/${selected.id}/items`, {
          method: "POST",
          json: { symbol: symbol.symbol },
        }),
      );
    });

  const removeSymbol = (symbol: string) =>
    run(async () => {
      if (!selected) return;
      await authRequest<void>(`/api/v1/watchlists/${selected.id}/items/${encodeURIComponent(symbol)}`, {
        method: "DELETE",
      });
      replace({ ...selected, symbols: selected.symbols.filter((s) => s.symbol !== symbol) });
    });

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-1">
        <div className="flex flex-wrap items-center gap-1" role="tablist" aria-label="Your watchlists">
          {lists.map((w) => (
          <button
            key={w.id}
            type="button"
            role="tab"
            aria-selected={w.id === selected?.id}
            onClick={() => setSelectedId(w.id)}
            className={`tab ${w.id === selected?.id ? "" : "border-border"}`}
          >
            {w.name} <span className="tabular">({w.symbols.length})</span>
          </button>
          ))}
        </div>
        <NameForm label="New list" placeholder="List name" submitLabel="Create" disabled={busy} onSubmit={createList} />
      </div>

      {actionError && (
        <p role="alert" className="notice text-down">
          {actionError}
        </p>
      )}

      {!selected ? (
        <EmptyState title="You don't have any watchlists yet">Create one above to start tracking symbols.</EmptyState>
      ) : (
        <Card
          flush
          title={selected.name}
          action={
            <div className="flex flex-wrap items-center gap-2">
              <NameForm
                key={selected.id}
                label="Rename"
                placeholder="New name"
                submitLabel="Save"
                initial={selected.name}
                disabled={busy}
                onSubmit={renameList}
              />
              <button
                type="button"
                onClick={() => setConfirmDelete(true)}
                className="btn btn-danger"
              >
                Delete list
              </button>
            </div>
          }
        >
          <div className="max-w-md p-3">
            <SearchBox onSelect={addSymbol} placeholder="Add a symbol…" label={`Add a symbol to ${selected.name}`} />
          </div>
          <WatchlistTable watchlist={selected} onRemove={removeSymbol} busy={busy} />
        </Card>
      )}

      <ConfirmDialog
        open={confirmDelete}
        title={`Delete “${selected?.name ?? ""}”?`}
        body="This removes the list and its symbols. It can't be undone."
        confirmLabel="Delete list"
        busy={busy}
        onConfirm={deleteList}
        onCancel={() => setConfirmDelete(false)}
      />
    </div>
  );
}

function WatchlistTable({
  watchlist,
  onRemove,
  busy,
}: {
  watchlist: Watchlist;
  onRemove: (symbol: string) => void;
  busy: boolean;
}) {
  const symbols = watchlist.symbols.map((s) => s.symbol);
  const quotes = useBulkQuotes(symbols);
  if (watchlist.symbols.length === 0) {
    return (
      <div className="px-3 pb-3">
        <EmptyState title="This watchlist is empty">Search above to add stocks, ETFs or forex pairs.</EmptyState>
      </div>
    );
  }
  if (quotes.state.kind === "error") {
    return (
      <div className="px-3 pb-3">
        <ErrorState message={quotes.state.error.message} retryable={quotes.state.error.retryable} onRetry={quotes.reload} />
      </div>
    );
  }
  const bySymbol = quotes.state.kind === "ready" ? quotes.state.bySymbol : null;
  const streamable = watchlist.symbols.filter((s) => s.streamable).map((s) => s.symbol);

  return (
    <LiveQuotesProvider symbols={streamable}>
      <div className="overflow-x-auto border-t border-border">
        <table className="data-table sm:min-w-[32rem]">
          <caption className="sr-only">Symbols in {watchlist.name}</caption>
          <thead>
            <tr>
              <th scope="col">Symbol</th>
              <th scope="col" className="max-sm:hidden">Name</th>
              <th scope="col" className="num">Price</th>
              <th scope="col" className="num">Change</th>
              <th scope="col" className="num"><span className="sr-only">Actions</span></th>
            </tr>
          </thead>
          <tbody>
            {watchlist.symbols.map((symbol) => (
              <WatchlistRow
                key={symbol.symbol}
                symbol={symbol}
                result={bySymbol ? (bySymbol[symbol.symbol] ?? null) : undefined}
                onRemove={onRemove}
                busy={busy}
              />
            ))}
          </tbody>
        </table>
      </div>
    </LiveQuotesProvider>
  );
}

function WatchlistRow({
  symbol,
  result,
  onRemove,
  busy,
}: {
  symbol: SymbolInfo;
  /** undefined while loading, null if missing from the response */
  result: QuoteResult | null | undefined;
  onRemove: (symbol: string) => void;
  busy: boolean;
}) {
  const { trades } = useSharedLiveQuotes();
  const envelope = result?.quote ?? null;
  const display = mergeLiveTrade(envelope?.data ?? null, trades[symbol.symbol]);
  const currency = envelope?.data.currency ?? symbol.currency;

  return (
    <tr>
      <td>
        <Link href={`/stock/${encodeURIComponent(symbol.symbol)}`} className="font-medium text-primary hover:text-accent">
          {symbol.display_symbol}
        </Link>
      </td>
      <td className="max-w-56 truncate text-secondary max-sm:hidden" title={symbol.description}>
        {symbol.description}
      </td>
      {result === undefined ? (
        <>
          <td className="num"><Skeleton className="ml-auto h-3.5 w-16" /></td>
          <td className="num"><Skeleton className="ml-auto h-3.5 w-14" /></td>
        </>
      ) : display ? (
        <>
          <td className="num text-primary">
            <PriceTick value={display.price}>{formatPrice(display.price, currency)}</PriceTick>
            {symbol.quote_delay_min !== null && (
              <span className="ml-1 text-2xs text-muted" title={`Delayed up to ${symbol.quote_delay_min} minutes`}>
                delayed
              </span>
            )}
            {envelope?.stale && (
              <span className="ml-1 align-middle">
                <StaleBadge asOf={envelope.as_of} stale />
              </span>
            )}
          </td>
          <td className="num">
            <ChangeText changePct={display.changePct} />
          </td>
        </>
      ) : (
        <td colSpan={2} className="num text-xs text-muted" title={symbol.price_note ?? undefined}>
          {QUOTE_ERROR_TEXT[result?.error ?? "provider_error"]}
          {symbol.price_note && <span className="sr-only">: {symbol.price_note}</span>}
        </td>
      )}
      <td className="num">
        <button
          type="button"
          disabled={busy}
          onClick={() => onRemove(symbol.symbol)}
          aria-label={`Remove ${symbol.display_symbol}`}
          className="rounded-sm px-1.5 text-xs text-secondary hover:text-down disabled:opacity-50"
        >
          Remove
        </button>
      </td>
    </tr>
  );
}

function NameForm({
  label,
  placeholder,
  submitLabel,
  initial = "",
  disabled,
  onSubmit,
}: {
  label: string;
  placeholder: string;
  submitLabel: string;
  initial?: string;
  disabled: boolean;
  onSubmit: (name: string) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(initial);
  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="btn"
      >
        {label}
      </button>
    );
  }
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim()) return;
    await onSubmit(name);
    setOpen(false);
  };
  return (
    <form onSubmit={submit} className="flex items-center gap-1">
      <input
        autoFocus
        aria-label={label}
        value={name}
        maxLength={60}
        placeholder={placeholder}
        onChange={(event) => setName(event.target.value)}
        onKeyDown={(event) => event.key === "Escape" && setOpen(false)}
        className="input w-36 py-0.5 text-xs"
      />
      <button type="submit" disabled={disabled} className="btn btn-primary">
        {submitLabel}
      </button>
      <button type="button" onClick={() => setOpen(false)} className="px-1 text-xs text-secondary hover:text-primary">
        Cancel
      </button>
    </form>
  );
}

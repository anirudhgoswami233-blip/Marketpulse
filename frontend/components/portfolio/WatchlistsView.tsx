"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";

import { useBulkQuotes } from "@/components/portfolio/useBulkQuotes";
import { LiveQuotesProvider, useSharedLiveQuotes } from "@/components/markets/LiveQuotesProvider";
import { SearchBox } from "@/components/search/SearchBox";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Card, ChangeText, EmptyState, Skeleton, SkeletonBlock } from "@/components/ui/primitives";
import { ErrorState, StaleBadge } from "@/components/ui/status";
import { toApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatPrice } from "@/lib/format";
import { mergeLiveTrade } from "@/lib/quotes";
import { useAuthedQuery } from "@/lib/useAuthedQuery";
import type { QuoteResult, SymbolInfo, Watchlist } from "@/types/api";

const QUOTE_ERROR_TEXT: Record<NonNullable<QuoteResult["error"]>, string> = {
  unavailable: "Not on our data plan",
  not_found: "Unknown symbol",
  provider_error: "Price unavailable",
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
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2" role="tablist" aria-label="Your watchlists">
        {lists.map((w) => (
          <button
            key={w.id}
            type="button"
            role="tab"
            aria-selected={w.id === selected?.id}
            onClick={() => setSelectedId(w.id)}
            className={`rounded-full px-3 py-1 text-sm ${
              w.id === selected?.id ? "bg-accent text-surface" : "border border-border text-secondary hover:text-primary"
            }`}
          >
            {w.name} <span className="opacity-70">({w.symbols.length})</span>
          </button>
        ))}
        <NameForm label="New list" placeholder="List name" submitLabel="Create" disabled={busy} onSubmit={createList} />
      </div>

      {actionError && (
        <p role="alert" className="rounded-md bg-surface-2 px-3 py-2 text-sm text-down">
          {actionError}
        </p>
      )}

      {!selected ? (
        <EmptyState title="You don't have any watchlists yet">Create one above to start tracking symbols.</EmptyState>
      ) : (
        <Card
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
                className="rounded-md border border-border px-2.5 py-1 text-xs text-down hover:bg-surface-2"
              >
                Delete list
              </button>
            </div>
          }
        >
          <div className="mb-4 max-w-md">
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
    return <EmptyState title="This watchlist is empty">Search above to add stocks, ETFs or forex pairs.</EmptyState>;
  }
  if (quotes.state.kind === "error") {
    return <ErrorState message={quotes.state.error.message} retryable={quotes.state.error.retryable} onRetry={quotes.reload} />;
  }
  const bySymbol = quotes.state.kind === "ready" ? quotes.state.bySymbol : null;
  const streamable = watchlist.symbols.filter((s) => s.streamable).map((s) => s.symbol);

  return (
    <LiveQuotesProvider symbols={streamable}>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[32rem] text-sm">
          <caption className="sr-only">Symbols in {watchlist.name}</caption>
          <thead>
            <tr className="text-left text-xs text-muted">
              <th scope="col" className="pb-2 font-normal">Symbol</th>
              <th scope="col" className="pb-2 font-normal">Name</th>
              <th scope="col" className="pb-2 text-right font-normal">Price</th>
              <th scope="col" className="pb-2 text-right font-normal">Change</th>
              <th scope="col" className="pb-2 text-right font-normal"><span className="sr-only">Actions</span></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
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
      <td className="py-2">
        <Link href={`/stock/${encodeURIComponent(symbol.symbol)}`} className="font-medium text-primary hover:text-accent">
          {symbol.display_symbol}
        </Link>
      </td>
      <td className="max-w-56 truncate py-2 text-secondary" title={symbol.description}>
        {symbol.description}
      </td>
      {result === undefined ? (
        <>
          <td className="py-2 text-right"><Skeleton className="ml-auto h-4 w-16" /></td>
          <td className="py-2 text-right"><Skeleton className="ml-auto h-4 w-14" /></td>
        </>
      ) : display ? (
        <>
          <td className="tabular py-2 text-right text-primary">
            {formatPrice(display.price, currency)}
            {envelope?.stale && (
              <span className="ml-1 align-middle">
                <StaleBadge asOf={envelope.as_of} stale />
              </span>
            )}
          </td>
          <td className="py-2 text-right">
            <ChangeText changePct={display.changePct} />
          </td>
        </>
      ) : (
        <td colSpan={2} className="py-2 text-right text-xs text-muted">
          {QUOTE_ERROR_TEXT[result?.error ?? "provider_error"]}
        </td>
      )}
      <td className="py-2 text-right">
        <button
          type="button"
          disabled={busy}
          onClick={() => onRemove(symbol.symbol)}
          aria-label={`Remove ${symbol.display_symbol}`}
          className="rounded px-2 py-0.5 text-xs text-muted hover:bg-surface-2 hover:text-down disabled:opacity-50"
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
        className="rounded-md border border-dashed border-border px-2.5 py-1 text-xs text-secondary hover:text-primary"
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
        className="w-36 rounded-md border border-border bg-surface px-2 py-1 text-xs text-primary focus:border-accent focus:outline-none"
      />
      <button type="submit" disabled={disabled} className="rounded-md bg-accent px-2 py-1 text-xs font-medium text-surface disabled:opacity-60">
        {submitLabel}
      </button>
      <button type="button" onClick={() => setOpen(false)} className="px-1 text-xs text-muted hover:text-primary">
        Cancel
      </button>
    </form>
  );
}

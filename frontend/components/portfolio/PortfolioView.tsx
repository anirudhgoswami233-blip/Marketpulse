"use client";

import Link from "next/link";
import { useState } from "react";

import { LiveQuotesProvider, useSharedLiveQuotes } from "@/components/markets/LiveQuotesProvider";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Card, ChangeText, EmptyState, SkeletonBlock } from "@/components/ui/primitives";
import { ErrorState, LocalTime, StaleBadge } from "@/components/ui/status";
import { toApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatChange, formatMoney, formatNumber, formatPrice } from "@/lib/format";
import { liveTotals, revaluePosition } from "@/lib/portfolio";
import { useAuthedQuery } from "@/lib/useAuthedQuery";
import type { Portfolio, Trade } from "@/types/api";

export function PortfolioView() {
  const { authRequest } = useAuth();
  const portfolio = useAuthedQuery<Portfolio>("/api/v1/portfolio");
  const trades = useAuthedQuery<Trade[]>("/api/v1/portfolio/trades");
  const [confirmReset, setConfirmReset] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [resetError, setResetError] = useState<string | null>(null);

  if (portfolio.state.kind === "loading") return <SkeletonBlock lines={10} label="Loading portfolio" />;
  if (portfolio.state.kind === "error") {
    const { error } = portfolio.state;
    return <ErrorState message={error.message} retryable={error.retryable} onRetry={portfolio.reload} />;
  }
  const data = portfolio.state.data;

  const reset = async () => {
    setResetting(true);
    setResetError(null);
    try {
      portfolio.mutate(await authRequest<Portfolio>("/api/v1/portfolio/reset", { method: "POST" }));
      trades.mutate([]);
      setConfirmReset(false);
    } catch (error) {
      setResetError(toApiError(error).message);
    } finally {
      setResetting(false);
    }
  };

  return (
    <LiveQuotesProvider symbols={data.positions.map((p) => p.symbol)}>
      <div className="space-y-6">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-sm text-secondary">
            Virtual money only. Orders fill at the current market price; place them from any stock page.
          </p>
          <button
            type="button"
            onClick={() => setConfirmReset(true)}
            className="rounded-md border border-border px-3 py-1.5 text-xs text-down hover:bg-surface-2"
          >
            Reset portfolio
          </button>
        </div>
        {resetError && (
          <p role="alert" className="rounded-md bg-surface-2 px-3 py-2 text-sm text-down">
            {resetError}
          </p>
        )}
        <Holdings portfolio={data} />
        <Card title="Trade history">
          <TradeHistory state={trades.state} onRetry={trades.reload} />
        </Card>
      </div>
      <ConfirmDialog
        open={confirmReset}
        title="Reset your paper portfolio?"
        body={`This clears all positions and trade history and restores your cash to ${formatMoney(
          data.starting_cash,
          data.base_currency,
        )}. It can't be undone.`}
        confirmLabel="Reset portfolio"
        busy={resetting}
        onConfirm={reset}
        onCancel={() => setConfirmReset(false)}
      />
    </LiveQuotesProvider>
  );
}

function Holdings({ portfolio }: { portfolio: Portfolio }) {
  const { trades } = useSharedLiveQuotes();
  const positions = portfolio.positions.map((p) => revaluePosition(p, trades[p.symbol]));
  const totals = liveTotals(portfolio, positions);
  const ccy = portfolio.base_currency;

  return (
    <>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Total equity" value={formatMoney(totals.equity, ccy)} />
        <Stat label="Cash" value={formatMoney(portfolio.cash, ccy)} />
        <Stat
          label="Total return"
          value={formatMoney(totals.totalReturn, ccy)}
          extra={<ChangeText changePct={totals.totalReturnPct?.toFixed(4) ?? null} className="text-xs" />}
        />
        <Stat label="Realized P&L" value={formatMoney(portfolio.realized_pnl, ccy)} />
      </div>
      {portfolio.incomplete && (
        <p className="text-xs text-muted">
          Some positions couldn&apos;t be priced right now and are counted at cost.
        </p>
      )}
      <Card title="Positions">
        {positions.length === 0 ? (
          <EmptyState title="No positions yet">
            Open any US stock or ETF page, for example{" "}
            <Link href="/stock/SPY" className="text-accent hover:underline">
              SPY
            </Link>
            , and use the Trade panel.
          </EmptyState>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[40rem] text-sm">
              <caption className="sr-only">Open positions</caption>
              <thead>
                <tr className="text-left text-xs text-muted">
                  <th scope="col" className="pb-2 font-normal">Symbol</th>
                  <th scope="col" className="pb-2 text-right font-normal">Quantity</th>
                  <th scope="col" className="pb-2 text-right font-normal">Avg cost</th>
                  <th scope="col" className="pb-2 text-right font-normal">Price</th>
                  <th scope="col" className="pb-2 text-right font-normal">Market value</th>
                  <th scope="col" className="pb-2 text-right font-normal">Unrealized P&amp;L</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {positions.map(({ position: p, price, marketValue, unrealizedPnl, unrealizedPnlPct, live }) => (
                  <tr key={p.symbol}>
                    <td className="py-2">
                      <Link href={`/stock/${encodeURIComponent(p.symbol)}`} className="font-medium text-primary hover:text-accent">
                        {p.display_symbol}
                      </Link>
                      <span className="block max-w-48 truncate text-xs text-muted">{p.description}</span>
                    </td>
                    <td className="tabular py-2 text-right">{formatNumber(p.quantity, 6)}</td>
                    <td className="tabular py-2 text-right">{formatPrice(p.avg_cost, p.currency)}</td>
                    <td className="tabular py-2 text-right">
                      {price === null ? "—" : formatPrice(price, p.currency)}
                      {live && <span className="ml-1 text-xs text-up" aria-label="live">●</span>}
                      {!live && p.price_stale && p.price_as_of && (
                        <span className="ml-1 align-middle">
                          <StaleBadge asOf={p.price_as_of} stale />
                        </span>
                      )}
                    </td>
                    <td className="tabular py-2 text-right">
                      {marketValue === null ? "—" : formatMoney(marketValue, p.currency)}
                    </td>
                    <td className="py-2 text-right">
                      {unrealizedPnl === null ? (
                        "—"
                      ) : (
                        <ChangeText change={unrealizedPnl.toFixed(2)} changePct={unrealizedPnlPct?.toFixed(4) ?? null} />
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}

function Stat({ label, value, extra }: { label: string; value: string; extra?: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <p className="text-xs text-muted">{label}</p>
      <p className="tabular mt-1 text-lg font-semibold text-primary">{value}</p>
      {extra}
    </div>
  );
}

function TradeHistory({
  state,
  onRetry,
}: {
  state: ReturnType<typeof useAuthedQuery<Trade[]>>["state"];
  onRetry: () => void;
}) {
  if (state.kind === "loading") return <SkeletonBlock lines={4} label="Loading trades" />;
  if (state.kind === "error") return <ErrorState message={state.error.message} retryable={state.error.retryable} onRetry={onRetry} />;
  if (state.data.length === 0) return <EmptyState title="No trades yet" />;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[36rem] text-sm">
        <caption className="sr-only">Trade history, newest first</caption>
        <thead>
          <tr className="text-left text-xs text-muted">
            <th scope="col" className="pb-2 font-normal">Time</th>
            <th scope="col" className="pb-2 font-normal">Side</th>
            <th scope="col" className="pb-2 font-normal">Symbol</th>
            <th scope="col" className="pb-2 text-right font-normal">Quantity</th>
            <th scope="col" className="pb-2 text-right font-normal">Price</th>
            <th scope="col" className="pb-2 text-right font-normal">Total</th>
            <th scope="col" className="pb-2 text-right font-normal">Realized</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {state.data.map((t) => (
            <tr key={t.id}>
              <td className="py-2 text-xs text-secondary">
                <LocalTime iso={t.executed_at} withDate />
              </td>
              <td className={`py-2 text-xs font-medium uppercase ${t.side === "buy" ? "text-up" : "text-down"}`}>{t.side}</td>
              <td className="py-2">{t.display_symbol}</td>
              <td className="tabular py-2 text-right">{formatNumber(t.quantity, 6)}</td>
              <td className="tabular py-2 text-right">{formatPrice(t.price, t.currency)}</td>
              <td className="tabular py-2 text-right">{formatMoney(t.notional, t.currency)}</td>
              <td className="tabular py-2 text-right">{t.realized_pnl === null ? "—" : formatChange(t.realized_pnl)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

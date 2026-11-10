"use client";

import Link from "next/link";
import { useState } from "react";

import { LiveQuotesProvider, useSharedLiveQuotes } from "@/components/markets/LiveQuotesProvider";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { PriceTick } from "@/components/ui/PriceTick";
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
      <div className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-[13px] text-secondary">
            Virtual money only. Orders fill at the current market price; place them from any stock page.
          </p>
          <button
            type="button"
            onClick={() => setConfirmReset(true)}
            className="btn btn-danger"
          >
            Reset portfolio
          </button>
        </div>
        {resetError && (
          <p role="alert" className="notice text-down">
            {resetError}
          </p>
        )}
        <Holdings portfolio={data} />
        <Card title="Trade history" flush>
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
      <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-md border border-border bg-border lg:grid-cols-4">
        <Stat label="Total equity" value={formatMoney(totals.equity, ccy)} />
        <Stat label="Cash" value={formatMoney(portfolio.cash, ccy)} />
        <Stat
          label="Total return"
          value={formatMoney(totals.totalReturn, ccy)}
          extra={<ChangeText changePct={totals.totalReturnPct?.toFixed(4) ?? null} className="text-xs font-normal" />}
        />
        <Stat label="Realized P&L" value={formatMoney(portfolio.realized_pnl, ccy)} />
      </dl>
      {portfolio.incomplete && (
        <p className="text-xs text-muted">
          Some positions couldn&apos;t be priced right now and are counted at cost.
        </p>
      )}
      <Card title="Positions" flush>
        {positions.length === 0 ? (
          <div className="p-3">
            <EmptyState title="No positions yet">
              Open any US stock or ETF page, for example{" "}
              <Link href="/stock/SPY" className="text-accent hover:underline">
                SPY
              </Link>
              , and use the Trade panel.
            </EmptyState>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="data-table min-w-[40rem]">
              <caption className="sr-only">Open positions</caption>
              <thead>
                <tr>
                  <th scope="col">Symbol</th>
                  <th scope="col" className="num">Quantity</th>
                  <th scope="col" className="num">Avg cost</th>
                  <th scope="col" className="num">Price</th>
                  <th scope="col" className="num">Market value</th>
                  <th scope="col" className="num">Unrealized P&amp;L</th>
                </tr>
              </thead>
              <tbody>
                {positions.map(({ position: p, price, marketValue, unrealizedPnl, unrealizedPnlPct, live }) => (
                  <tr key={p.symbol}>
                    <td>
                      <Link href={`/stock/${encodeURIComponent(p.symbol)}`} className="font-medium text-primary hover:text-accent">
                        {p.display_symbol}
                      </Link>{" "}
                      <span className="inline-block max-w-48 truncate align-bottom text-2xs text-muted">{p.description}</span>
                    </td>
                    <td className="num">{formatNumber(p.quantity, 6)}</td>
                    <td className="num">{formatPrice(p.avg_cost, p.currency)}</td>
                    <td className="num">
                      {live && <span className="mr-1 text-[0.6em] text-up" role="img" aria-label="live">●</span>}
                      {price === null ? "—" : <PriceTick value={price}>{formatPrice(price, p.currency)}</PriceTick>}
                      {!live && p.price_stale && p.price_as_of && (
                        <span className="ml-1 align-middle">
                          <StaleBadge asOf={p.price_as_of} stale />
                        </span>
                      )}
                    </td>
                    <td className="num">
                      {marketValue === null ? "—" : formatMoney(marketValue, p.currency)}
                    </td>
                    <td className="num">
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
    <div className="bg-surface px-3 py-2">
      <dt className="section-label">{label}</dt>
      <dd className="tabular mt-0.5 flex flex-wrap items-baseline gap-x-2 text-base font-semibold text-primary">
        {value}
        {extra}
      </dd>
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
  if (state.kind !== "ready" || state.data.length === 0) {
    return (
      <div className="p-3">
        {state.kind === "loading" ? (
          <SkeletonBlock lines={4} label="Loading trades" />
        ) : state.kind === "error" ? (
          <ErrorState message={state.error.message} retryable={state.error.retryable} onRetry={onRetry} />
        ) : (
          <EmptyState title="No trades yet" />
        )}
      </div>
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="data-table min-w-[36rem]">
        <caption className="sr-only">Trade history, newest first</caption>
        <thead>
          <tr>
            <th scope="col">Time</th>
            <th scope="col">Side</th>
            <th scope="col">Symbol</th>
            <th scope="col" className="num">Quantity</th>
            <th scope="col" className="num">Price</th>
            <th scope="col" className="num">Total</th>
            <th scope="col" className="num">Realized</th>
          </tr>
        </thead>
        <tbody>
          {state.data.map((t) => (
            <tr key={t.id}>
              <td className="text-xs whitespace-nowrap text-secondary">
                <LocalTime iso={t.executed_at} withDate />
              </td>
              <td className={`text-xs font-medium uppercase ${t.side === "buy" ? "text-up" : "text-down"}`}>{t.side}</td>
              <td className="font-medium">{t.display_symbol}</td>
              <td className="num">{formatNumber(t.quantity, 6)}</td>
              <td className="num">{formatPrice(t.price, t.currency)}</td>
              <td className="num">{formatMoney(t.notional, t.currency)}</td>
              <td className="num">{t.realized_pnl === null ? "—" : formatChange(t.realized_pnl)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

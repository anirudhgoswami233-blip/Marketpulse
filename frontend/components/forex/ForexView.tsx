"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Card, ChangeText, EmptyState, Skeleton, SkeletonBlock } from "@/components/ui/primitives";
import { ErrorState, LocalTime, StaleBadge } from "@/components/ui/status";
import { useAuthedQuery } from "@/lib/useAuthedQuery";
import type { ForexBoard, ForexRow } from "@/types/api";

const POLL_MS = 4000;

/** Rates span 0.005 (JPY/INR) to 350,000 (XAU/INR): keep ~6 significant digits. */
export function formatRate(value: number | string | null): string {
  if (value === null) return "—";
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return "—";
  const digits = n >= 1000 ? 2 : n >= 1 ? 4 : 6;
  return new Intl.NumberFormat(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(n);
}

/** Convert using "USD per unit" values; display-only arithmetic. */
export function convertAmount(amount: number, from: string, to: string, usdPerUnit: Record<string, string>): number | null {
  const a = Number(usdPerUnit[from]);
  const b = Number(usdPerUnit[to]);
  if (!Number.isFinite(amount) || !a || !b) return null;
  return (amount * a) / b;
}

export function ForexView() {
  // Public data; useAuthedQuery just adds the token when signed in.
  const { state, reload } = useAuthedQuery<ForexBoard>("/api/v1/forex");
  const warming = state.kind === "ready" && (state.data.refreshing || state.data.as_of === null);

  // The first visit after a server restart starts a background refresh; poll until it lands.
  useEffect(() => {
    if (!warming) return;
    const id = window.setInterval(reload, POLL_MS);
    return () => window.clearInterval(id);
  }, [warming, reload]);

  if (state.kind === "loading") return <ForexSkeleton />;
  if (state.kind === "error") {
    return <ErrorState message={state.error.message} retryable={state.error.retryable} onRetry={reload} />;
  }
  const board = state.data;
  const groups = [...new Set(board.rows.map((r) => r.group))];
  const priced = board.rows.some((r) => r.rate !== null);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
        {board.as_of ? (
          <span>
            Updated <LocalTime iso={board.as_of} /> · refreshed every {board.refresh_interval_min} minutes while forex trades
          </span>
        ) : (
          <span role="status">Fetching the latest rates. This takes a minute or two after a restart…</span>
        )}
        <StaleBadge asOf={board.as_of} stale={board.stale} />
      </div>

      {!priced && board.as_of !== null ? (
        <EmptyState title="Rates aren't available right now">
          Our forex data provider didn&apos;t return any rates. Try again later.
        </EmptyState>
      ) : (
        <div className="grid items-start gap-3 lg:grid-cols-[2fr_1fr]">
          <div className="space-y-3">
            <div className="grid items-start gap-3 sm:grid-cols-2">
              {groups.map((group) => (
                <Card key={group} title={group} flush>
                  <RateTable rows={board.rows.filter((r) => r.group === group)} loading={!priced} group={group} />
                </Card>
              ))}
            </div>
            <p className="text-xs text-muted">
              <span className="font-medium">≈</span> marks cross rates derived from two USD pairs (e.g. EUR/INR from
              EUR/USD and USD/INR). Quotes come from Twelve Data and are indicative, not dealable prices.
            </p>
          </div>
          <Card title="Currency converter">
            <Converter board={board} />
          </Card>
        </div>
      )}
    </div>
  );
}

/** Mirrors the loaded layout (status line, rate tables, converter) so content doesn't jump when rates arrive. */
function ForexSkeleton() {
  return (
    <div className="space-y-3" role="status" aria-label="Loading forex rates">
      <Skeleton className="h-4 w-64 max-w-full" />
      <div className="grid items-start gap-3 lg:grid-cols-[2fr_1fr]">
        <div className="grid items-start gap-3 sm:grid-cols-2">
          {Array.from({ length: 4 }, (_, i) => (
            <Card key={i}>
              <SkeletonBlock lines={7} label="Loading rates" />
            </Card>
          ))}
        </div>
        <Card>
          <SkeletonBlock lines={9} label="Loading converter" />
        </Card>
      </div>
    </div>
  );
}

function RateTable({ rows, loading, group }: { rows: ForexRow[]; loading: boolean; group: string }) {
  return (
    <table className="data-table">
      <caption className="sr-only">{group} rates</caption>
      <thead>
        <tr>
          <th scope="col">Pair</th>
          <th scope="col" className="num">Rate</th>
          <th scope="col" className="num">Change</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.pair}>
            <td>
              {row.symbol ? (
                <Link href={`/stock/${encodeURIComponent(row.symbol)}`} className="font-medium text-primary hover:text-accent">
                  {row.pair}
                </Link>
              ) : (
                <span className="font-medium text-primary">{row.pair}</span>
              )}
              {row.derived && (
                <span className="ml-1 text-xs text-muted" title="Derived from two USD pairs">
                  ≈<span className="sr-only"> derived cross rate</span>
                </span>
              )}
            </td>
            <td className="num text-primary">
              {loading ? <span className="text-muted">…</span> : formatRate(row.rate)}
            </td>
            <td className="num">
              {row.change_pct === null ? <span className="text-muted">—</span> : <ChangeText changePct={row.change_pct} />}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Converter({ board }: { board: ForexBoard }) {
  const available = board.currencies.filter((c) => board.usd_per_unit[c.code]);
  const [amount, setAmount] = useState("100");
  const [from, setFrom] = useState("USD");
  const [to, setTo] = useState("INR");
  if (available.length < 2) return <p className="text-sm text-muted">The converter appears once rates load.</p>;

  const value = Number(amount);
  const result = amount.trim() === "" ? null : convertAmount(value, from, to, board.usd_per_unit);
  const unit = convertAmount(1, from, to, board.usd_per_unit);
  const selectClass = "input";

  return (
    <form className="space-y-2 text-[13px]" onSubmit={(e) => e.preventDefault()}>
      <label className="block space-y-1">
        <span className="text-secondary">Amount</span>
        <input
          inputMode="decimal"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          className="input"
        />
      </label>
      {/* Stacked: the converter sits in a narrow column, and side-by-side selects truncate currency names. */}
      <div className="grid grid-cols-1 gap-2">
        <label className="block space-y-1">
          <span className="text-secondary">From</span>
          <select value={from} onChange={(e) => setFrom(e.target.value)} className={selectClass}>
            {available.map((c) => (
              <option key={c.code} value={c.code}>
                {c.code}: {c.name}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          onClick={() => {
            setFrom(to);
            setTo(from);
          }}
          aria-label="Swap currencies"
          className="btn justify-self-start"
        >
          ⇅ Swap
        </button>
        <label className="block space-y-1">
          <span className="text-secondary">To</span>
          <select value={to} onChange={(e) => setTo(e.target.value)} className={selectClass}>
            {available.map((c) => (
              <option key={c.code} value={c.code}>
                {c.code}: {c.name}
              </option>
            ))}
          </select>
        </label>
      </div>
      <output className="block rounded-sm border border-border bg-surface-2 px-3 py-2" aria-live="polite">
        {result === null || !Number.isFinite(value) ? (
          <span className="text-muted">Enter an amount</span>
        ) : (
          <>
            <span className="tabular text-base font-semibold text-primary">
              {formatRate(result)} {to}
            </span>
            <span className="mt-0.5 block text-xs text-muted">
              1 {from} = {formatRate(unit)} {to}
            </span>
          </>
        )}
      </output>
      <p className="text-xs text-muted">Indicative mid-market rates for information only.</p>
    </form>
  );
}

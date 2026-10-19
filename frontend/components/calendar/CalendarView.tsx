"use client";

import Link from "next/link";
import { useState } from "react";

import { Card, EmptyState, SkeletonBlock } from "@/components/ui/primitives";
import { ErrorState, StaleBadge } from "@/components/ui/status";
import { useAuth } from "@/lib/auth";
import { formatCompact, formatDate, formatNumber, formatPct, formatPrice } from "@/lib/format";
import { useAuthedQuery } from "@/lib/useAuthedQuery";
import type { EarningsRow, EarningsSession, EarningsWeek, IpoWeek } from "@/types/api";

const PAGE = 100;

const SESSION_LABEL: Record<EarningsSession, string> = {
  before_open: "Before open",
  after_close: "After close",
  during_market: "During market",
  unknown: "Time not set",
};

/** ISO date (YYYY-MM-DD) of `iso` shifted by `days`, computed in UTC so it never drifts a day. */
export function shiftDate(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

export function CalendarView({ initialTab, initialWeek }: { initialTab: "earnings" | "ipos"; initialWeek: string }) {
  const [tab, setTab] = useState(initialTab);
  const [week, setWeek] = useState(initialWeek);
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div role="tablist" aria-label="Calendar" className="flex gap-1">
          {(["earnings", "ipos"] as const).map((t) => (
            <button
              key={t}
              type="button"
              role="tab"
              aria-selected={tab === t}
              onClick={() => setTab(t)}
              className={`rounded-md px-3 py-1.5 text-sm ${tab === t ? "bg-accent text-surface" : "text-secondary hover:bg-surface-2"}`}
            >
              {t === "earnings" ? "Earnings" : "IPOs"}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2 text-sm">
          <button type="button" onClick={() => setWeek(shiftDate(week, -7))} className="rounded-md border border-border px-2 py-1 text-secondary hover:text-primary" aria-label="Previous week">
            ←
          </button>
          <button type="button" onClick={() => setWeek(new Date().toISOString().slice(0, 10))} className="rounded-md border border-border px-2 py-1 text-xs text-secondary hover:text-primary">
            This week
          </button>
          <button type="button" onClick={() => setWeek(shiftDate(week, 7))} className="rounded-md border border-border px-2 py-1 text-secondary hover:text-primary" aria-label="Next week">
            →
          </button>
        </div>
      </div>
      {tab === "earnings" ? <Earnings week={week} /> : <Ipos week={week} />}
    </div>
  );
}

function WeekHeading({ start, end }: { start: string; end: string }) {
  return (
    <span>
      Week of {formatDate(start)} – {formatDate(end)}
    </span>
  );
}

function Earnings({ week }: { week: string }) {
  const { status } = useAuth();
  const [watchlistOnly, setWatchlistOnly] = useState(false);
  const [filter, setFilter] = useState("");
  const [shown, setShown] = useState(PAGE);
  const signedIn = status === "authenticated";
  const query = `/api/v1/calendar/earnings?week=${week}${signedIn && watchlistOnly ? "&watchlist_only=true" : ""}`;
  const { state, reload } = useAuthedQuery<EarningsWeek>(status === "loading" ? null : query);

  const controls = (
    <div className="flex flex-wrap items-center gap-3 text-xs">
      <input
        type="search"
        value={filter}
        onChange={(e) => {
          setFilter(e.target.value);
          setShown(PAGE);
        }}
        placeholder="Filter by symbol or company"
        aria-label="Filter earnings by symbol or company"
        className="w-52 rounded-md border border-border bg-surface px-2 py-1 text-primary"
      />
      {signedIn ? (
        <label className="flex items-center gap-1 text-secondary">
          <input type="checkbox" checked={watchlistOnly} onChange={(e) => setWatchlistOnly(e.target.checked)} />
          My watchlists only
        </label>
      ) : (
        <span className="text-muted">
          <Link href="/login?next=/calendar" className="text-accent hover:underline">
            Sign in
          </Link>{" "}
          to filter by your watchlists
        </span>
      )}
    </div>
  );

  if (state.kind === "loading") return <SkeletonBlock lines={10} label="Loading earnings" />;
  if (state.kind === "error") return <ErrorState message={state.error.message} retryable={state.error.retryable} onRetry={reload} />;
  const data = state.data;
  const needle = filter.trim().toLowerCase();
  const events = needle
    ? data.events.filter((e) => e.symbol.toLowerCase().includes(needle) || (e.name ?? "").toLowerCase().includes(needle))
    : data.events;
  const days = [...new Set(events.slice(0, shown).map((e) => e.date))];

  return (
    <Card
      title={<WeekHeading start={data.week_start} end={data.week_end} />}
      action={controls}
    >
      <div className="mb-3 flex flex-wrap items-center gap-2 text-xs text-muted">
        <span>
          {data.total} {data.total === 1 ? "company reports" : "companies report"} this week
          {data.total > data.events.length && ` (showing the first ${data.events.length})`}
        </span>
        <StaleBadge asOf={data.as_of} stale={data.stale} />
      </div>
      {events.length === 0 ? (
        <EmptyState title={watchlistOnly ? "None of your watchlist companies report this week" : "No earnings found for this week"}>
          {needle && "Try a different filter."}
        </EmptyState>
      ) : (
        <div className="space-y-5">
          {days.map((day) => (
            <section key={day} aria-label={formatDate(day)}>
              <h3 className="mb-1 text-sm font-medium text-primary">{formatDate(day)}</h3>
              <EarningsTable rows={events.slice(0, shown).filter((e) => e.date === day)} />
            </section>
          ))}
          {events.length > shown && (
            <button type="button" onClick={() => setShown(shown + PAGE)} className="w-full rounded-md border border-border py-1.5 text-xs text-secondary hover:text-primary">
              Show more ({events.length - shown} remaining)
            </button>
          )}
        </div>
      )}
    </Card>
  );
}

function EarningsTable({ rows }: { rows: EarningsRow[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[40rem] text-sm">
        <thead>
          <tr className="text-left text-xs text-muted">
            <th scope="col" className="py-1 font-normal">Company</th>
            <th scope="col" className="py-1 font-normal">When</th>
            <th scope="col" className="py-1 text-right font-normal">EPS est.</th>
            <th scope="col" className="py-1 text-right font-normal">EPS actual</th>
            <th scope="col" className="py-1 text-right font-normal">Surprise</th>
            <th scope="col" className="py-1 text-right font-normal">Revenue est.</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {rows.map((e) => (
            <tr key={`${e.symbol}-${e.date}`}>
              <td className="py-1.5">
                <Link href={`/stock/${encodeURIComponent(e.symbol)}`} className="font-medium text-primary hover:text-accent">
                  {e.symbol}
                </Link>
                {e.in_watchlist && (
                  <span className="ml-1 text-xs text-accent" title="On one of your watchlists">
                    ★<span className="sr-only"> on your watchlist</span>
                  </span>
                )}
                {e.name && <span className="block max-w-56 truncate text-xs text-muted">{e.name}</span>}
              </td>
              <td className="py-1.5 text-xs text-secondary">{SESSION_LABEL[e.session]}</td>
              <td className="tabular py-1.5 text-right">{e.eps_estimate === null ? "—" : formatPrice(e.eps_estimate, "USD")}</td>
              <td className="tabular py-1.5 text-right">{e.eps_actual === null ? "—" : formatPrice(e.eps_actual, "USD")}</td>
              <td className="tabular py-1.5 text-right">{e.eps_surprise_pct === null ? "—" : formatPct(e.eps_surprise_pct)}</td>
              <td className="tabular py-1.5 text-right">{formatCompact(e.revenue_estimate, "USD")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Ipos({ week }: { week: string }) {
  const { state, reload } = useAuthedQuery<IpoWeek>(`/api/v1/calendar/ipos?week=${week}`);
  if (state.kind === "loading") return <SkeletonBlock lines={6} label="Loading IPOs" />;
  if (state.kind === "error") return <ErrorState message={state.error.message} retryable={state.error.retryable} onRetry={reload} />;
  const data = state.data;
  return (
    <Card title={<WeekHeading start={data.week_start} end={data.week_end} />} action={<StaleBadge asOf={data.as_of} stale={data.stale} />}>
      {data.events.length === 0 ? (
        <EmptyState title="No IPOs scheduled this week" />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[40rem] text-sm">
            <thead>
              <tr className="text-left text-xs text-muted">
                <th scope="col" className="py-1 font-normal">Date</th>
                <th scope="col" className="py-1 font-normal">Company</th>
                <th scope="col" className="py-1 font-normal">Exchange</th>
                <th scope="col" className="py-1 text-right font-normal">Price range</th>
                <th scope="col" className="py-1 text-right font-normal">Shares</th>
                <th scope="col" className="py-1 text-right font-normal">Deal size</th>
                <th scope="col" className="py-1 font-normal">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {data.events.map((e) => (
                <tr key={`${e.name}-${e.date}`}>
                  <td className="py-1.5 text-xs text-secondary">{formatDate(e.date)}</td>
                  <td className="py-1.5">
                    <span className="font-medium text-primary">{e.name}</span>
                    {e.symbol && <span className="ml-1 text-xs text-muted">{e.symbol}</span>}
                  </td>
                  <td className="py-1.5 text-xs text-secondary">{e.exchange ?? "—"}</td>
                  <td className="tabular py-1.5 text-right">{e.price_range ? `$${e.price_range}` : "—"}</td>
                  <td className="tabular py-1.5 text-right">{e.shares === null ? "—" : formatNumber(e.shares, 0)}</td>
                  <td className="tabular py-1.5 text-right">{formatCompact(e.total_value, "USD")}</td>
                  <td className="py-1.5 text-xs capitalize text-secondary">{e.status ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

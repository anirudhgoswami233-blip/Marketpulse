import Link from "next/link";
import { Suspense } from "react";

import { Disclaimer, SignalBadge, SignalCard } from "@/components/signals/SignalCard";
import { Card, EmptyState, SkeletonBlock } from "@/components/ui/primitives";
import { ErrorState } from "@/components/ui/status";
import { api, toApiError } from "@/lib/api";
import { formatPct } from "@/lib/format";
import type { LabelStats, Signal, SignalLabel, SignalPerformance } from "@/types/api";

export const metadata = { title: "Signal history" };

const LABELS: SignalLabel[] = ["Bullish signals", "Neutral", "Bearish signals"];
const HORIZONS = [1, 5, 20];

export default function SignalsPage({ searchParams }: PageProps<"/signals">) {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-primary">Signal history</h1>
        <p className="mt-1 max-w-3xl text-sm text-secondary">
          Every signal is stored with the price at the time, so you can check whether the labels have been useful. A
          bullish label counts as a hit if the price rose over the period; a bearish label if it fell.
        </p>
        <div className="mt-2">
          <Disclaimer />
        </div>
      </div>
      <Card title="How past signals performed">
        <Suspense fallback={<SkeletonBlock lines={6} label="Loading performance" />}>
          <Performance />
        </Suspense>
      </Card>
      <Suspense fallback={<SkeletonBlock lines={8} label="Loading signals" />}>
        <RecentSignals searchParams={searchParams} />
      </Suspense>
    </div>
  );
}

async function Performance() {
  let data: SignalPerformance;
  try {
    data = await api.signalPerformance();
  } catch (error) {
    const e = toApiError(error);
    return <ErrorState message={e.message} retryable={e.retryable} />;
  }
  const byKey = new Map(data.stats.map((s) => [`${s.label}|${s.horizon_days}`, s]));
  const measured = data.stats.reduce((n, s) => n + s.count, 0);
  if (measured === 0) {
    return (
      <EmptyState title="No results to measure yet">
        {data.total_signals === 0
          ? "Signals appear here once briefs or stock pages generate them."
          : `${data.total_signals} signal${data.total_signals === 1 ? " has" : "s have"} been recorded. Results appear after the next trading session closes.`}
      </EmptyState>
    );
  }
  return (
    <div className="space-y-3">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[36rem] text-sm">
          <caption className="sr-only">Average return and hit rate by label and holding period</caption>
          <thead>
            <tr className="text-left text-xs text-muted">
              <th scope="col" className="pb-2 font-normal">Label</th>
              {HORIZONS.map((h) => (
                <th key={h} scope="col" className="pb-2 text-right font-normal">
                  After {h} {h === 1 ? "day" : "days"}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {LABELS.map((label) => (
              <tr key={label}>
                <th scope="row" className="py-2 text-left font-normal">
                  <SignalBadge label={label} />
                </th>
                {HORIZONS.map((h) => (
                  <td key={h} className="py-2 text-right align-top">
                    <StatCell stats={byKey.get(`${label}|${h}`)} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-muted">
        Cells marked “small sample” have fewer than {data.min_sample} results and shouldn&apos;t be read as evidence either
        way. Past results don&apos;t predict future returns.
      </p>
    </div>
  );
}

function StatCell({ stats }: { stats: LabelStats | undefined }) {
  if (!stats || stats.count === 0) return <span className="text-muted">—</span>;
  return (
    <div className="tabular space-y-0.5">
      <div className="text-primary">avg {formatPct(stats.avg_return_pct)}</div>
      {stats.hit_rate_pct !== null && <div className="text-xs text-secondary">hit rate {Number(stats.hit_rate_pct).toFixed(1)}%</div>}
      <div className="text-xs text-muted">
        n = {stats.count}
        {!stats.enough_data && " · small sample"}
      </div>
    </div>
  );
}

async function RecentSignals({ searchParams }: { searchParams: PageProps<"/signals">["searchParams"] }) {
  const raw = (await searchParams).label;
  const label = LABELS.find((l) => l === (Array.isArray(raw) ? raw[0] : raw));
  let signals: Signal[];
  try {
    signals = await api.signalHistory({ label, limit: 50 });
  } catch (error) {
    const e = toApiError(error);
    return <ErrorState message={e.message} retryable={e.retryable} />;
  }
  return (
    <Card
      title="Recent signals"
      action={
        <nav aria-label="Filter by label" className="flex flex-wrap gap-1 text-xs">
          <FilterLink label={undefined} active={label === undefined} />
          {LABELS.map((l) => (
            <FilterLink key={l} label={l} active={label === l} />
          ))}
        </nav>
      }
    >
      {signals.length === 0 ? (
        <EmptyState title="No signals yet">
          Open a stock page such as <Link href="/stock/AAPL" className="text-accent hover:underline">AAPL</Link> or
          generate your daily brief.
        </EmptyState>
      ) : (
        <ul className="divide-y divide-border">
          {signals.map((signal) => (
            <li key={signal.id} className="py-4">
              <SignalCard signal={signal} showSymbol showDisclaimer={false} />
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function FilterLink({ label, active }: { label: SignalLabel | undefined; active: boolean }) {
  return (
    <Link
      href={label ? `/signals?label=${encodeURIComponent(label)}` : "/signals"}
      aria-current={active ? "page" : undefined}
      className={`rounded-full px-2.5 py-1 ${active ? "bg-accent text-surface" : "border border-border text-secondary hover:text-primary"}`}
    >
      {label ?? "All"}
    </Link>
  );
}

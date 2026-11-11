import Link from "next/link";
import { connection } from "next/server";
import { Suspense } from "react";

import { Disclaimer, SignalBadge, SignalCard } from "@/components/signals/SignalCard";
import { Card, EmptyState, PageHeader, SkeletonBlock } from "@/components/ui/primitives";
import { ErrorState } from "@/components/ui/status";
import { cachedSignalHistory, cachedSignalPerformance, toSettled } from "@/lib/cached";
import { formatPct } from "@/lib/format";
import type { LabelStats, SignalLabel } from "@/types/api";

export const metadata = { title: "Signal history" };

const LABELS: SignalLabel[] = ["Bullish signals", "Neutral", "Bearish signals"];
const HORIZONS = [1, 5, 20];

export default function SignalsPage({ searchParams }: PageProps<"/signals">) {
  return (
    <div className="space-y-3">
      <div>
        <PageHeader title="Signal history">
          Every signal is stored with the price at the time, so you can check whether the labels have been useful. A
          bullish label counts as a hit if the price rose over the period; a bearish label if it fell.
        </PageHeader>
        <div className="mt-1">
          <Disclaimer />
        </div>
      </div>
      <Card title="How past signals performed" flush>
        <Suspense
          fallback={
            <div className="p-3">
              <SkeletonBlock lines={6} label="Loading performance" />
            </div>
          }
        >
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
  // No params/searchParams here, so keep it dynamic to fill the cache at request time, not at build.
  await connection();
  const result = toSettled(await cachedSignalPerformance());
  if (result.error) {
    return (
      <div className="p-3">
        <ErrorState message={result.error.message} retryable={result.error.retryable} />
      </div>
    );
  }
  const data = result.data;
  const byKey = new Map(data.stats.map((s) => [`${s.label}|${s.horizon_days}`, s]));
  const measured = data.stats.reduce((n, s) => n + s.count, 0);
  if (measured === 0) {
    return (
      <div className="p-3">
        <EmptyState title="No results to measure yet">
          {data.total_signals === 0
            ? "Signals appear here once briefs or stock pages generate them."
            : `${data.total_signals} signal${data.total_signals === 1 ? " has" : "s have"} been recorded. Results appear after the next trading session closes.`}
        </EmptyState>
      </div>
    );
  }
  return (
    <div>
      <div className="overflow-x-auto">
        <table className="data-table min-w-[36rem]">
          <caption className="sr-only">Average return and hit rate by label and holding period</caption>
          <thead>
            <tr>
              <th scope="col">Label</th>
              {HORIZONS.map((h) => (
                <th key={h} scope="col" className="num">
                  After {h} {h === 1 ? "day" : "days"}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {LABELS.map((label) => (
              <tr key={label}>
                <th scope="row" className="font-normal">
                  <SignalBadge label={label} />
                </th>
                {HORIZONS.map((h) => (
                  <td key={h} className="num align-top">
                    <StatCell stats={byKey.get(`${label}|${h}`)} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="border-t border-border px-3 py-2 text-xs text-muted">
        Cells marked “small sample” have fewer than {data.min_sample} results and shouldn&apos;t be read as evidence either
        way. Past results don&apos;t predict future returns.
      </p>
    </div>
  );
}

function StatCell({ stats }: { stats: LabelStats | undefined }) {
  if (!stats || stats.count === 0) return <span className="text-muted">—</span>;
  return (
    <div className="tabular">
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
  // `searchParams` is read above (request-time), so this is already dynamic; the label is passed as the
  // cache key, not read inside the cached scope.
  const result = toSettled(await cachedSignalHistory(label));
  if (result.error) {
    return <ErrorState message={result.error.message} retryable={result.error.retryable} />;
  }
  const signals = result.data;
  return (
    <Card
      title="Recent signals"
      action={
        <nav aria-label="Filter by label" className="flex flex-wrap gap-0.5">
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
            <li key={signal.id} className="py-3 first:pt-0 last:pb-0">
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
      className="tab"
    >
      {label ?? "All"}
    </Link>
  );
}

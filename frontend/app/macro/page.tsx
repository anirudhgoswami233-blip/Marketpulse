import { Suspense } from "react";

import { MiniLineChart } from "@/components/macro/MiniLineChart";
import { Card, EmptyState, SkeletonBlock } from "@/components/ui/primitives";
import { ErrorState, StaleBadge } from "@/components/ui/status";
import { api, toApiError } from "@/lib/api";
import { formatDate } from "@/lib/format";
import type { MacroCard, MacroDashboard } from "@/types/api";

export const metadata = { title: "Macro" };

export default function MacroPage() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-semibold text-primary">Macro dashboard</h1>
        <p className="mt-1 text-sm text-secondary">
          Interest rates, inflation and jobs from the Federal Reserve Bank of St. Louis (FRED), over the last five years.
        </p>
      </div>
      <Suspense fallback={<MacroSkeleton />}>
        <Dashboard />
      </Suspense>
    </div>
  );
}

async function Dashboard() {
  let data: MacroDashboard;
  try {
    data = await api.macro();
  } catch (error) {
    const e = toApiError(error);
    return <ErrorState message={e.message} retryable={e.retryable} />;
  }
  if (!data.configured) {
    return (
      <EmptyState title="Macro data isn't set up">
        Add a free FRED_API_KEY to the backend&apos;s .env file to enable this dashboard.
      </EmptyState>
    );
  }
  const groups = [...new Set(data.cards.map((c) => c.group))];
  return (
    <div className="space-y-6">
      {groups.map((group) => (
        <section key={group} aria-labelledby={`group-${group}`}>
          <h2 id={`group-${group}`} className="mb-2 text-sm font-semibold tracking-wide text-secondary uppercase">
            {group}
          </h2>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            {data.cards
              .filter((c) => c.group === group)
              .map((card) => (
                <MacroCardView key={card.id} card={card} />
              ))}
          </div>
        </section>
      ))}
      <p className="text-xs text-muted">Source: FRED, Federal Reserve Bank of St. Louis. Updated as each series is published.</p>
    </div>
  );
}

function formatValue(value: string | null, unit: string): string {
  if (value === null) return "—";
  const n = Number(value);
  return unit === "%" ? `${n.toFixed(2)}%` : `${n.toFixed(2)} ${unit}`;
}

function MacroCardView({ card }: { card: MacroCard }) {
  if (card.error) {
    return (
      <Card title={card.title}>
        <ErrorState message={card.error} />
      </Card>
    );
  }
  const change = card.change === null ? null : Number(card.change);
  const unit = card.unit === "%" ? "pp" : card.unit;
  return (
    <Card title={card.title}>
      {card.latest ? (
        <div className="space-y-2">
          <div className="flex items-baseline justify-between gap-2">
            <span className="tabular text-2xl font-semibold text-primary">{formatValue(card.latest.value, card.unit)}</span>
            {change !== null && (
              <span className="tabular text-xs text-secondary">
                {change > 0 ? "▲" : change < 0 ? "▼" : "●"} {change > 0 ? "+" : ""}
                {change.toFixed(2)} {unit} vs prior
              </span>
            )}
          </div>
          <p className="text-xs text-muted">
            {formatDate(card.latest.date)}
            {card.transform === "yoy" && " · year-over-year change of the index"}
          </p>
          <MiniLineChart
            label={card.title}
            unit={card.unit}
            points={card.observations.map((p) => ({ date: p.date, value: Number(p.value) }))}
          />
          <StaleBadge asOf={card.as_of} stale={card.stale} />
        </div>
      ) : (
        <EmptyState title="No data yet" />
      )}
    </Card>
  );
}

function MacroSkeleton() {
  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4" role="status" aria-label="Loading macro data">
      {Array.from({ length: 8 }, (_, i) => (
        <Card key={i}>
          <SkeletonBlock lines={6} label="Loading series" />
        </Card>
      ))}
    </div>
  );
}

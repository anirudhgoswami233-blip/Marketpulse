import { Suspense } from "react";

import { IndexGrid } from "@/components/markets/IndexGrid";
import { LiveQuotesProvider } from "@/components/markets/LiveQuotesProvider";
import { MarketStatusList } from "@/components/markets/MarketStatusList";
import { MoversTable } from "@/components/markets/MoversTable";
import { SectorHeatmap } from "@/components/markets/SectorHeatmap";
import { BriefTeaser } from "@/components/signals/BriefTeaser";
import { AutoRefresh } from "@/components/ui/AutoRefresh";
import { Card, Skeleton, SkeletonBlock } from "@/components/ui/primitives";
import { ErrorState, LocalTime, StaleBadge } from "@/components/ui/status";
import { api, toApiError } from "@/lib/api";
import type { MarketOverview } from "@/types/api";

export default function MarketsPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-primary">Global markets</h1>
        <p className="mt-1 text-sm text-secondary">
          Regional indices are shown through US-listed ETFs that track them, so they move during US trading hours.
        </p>
      </div>
      <BriefTeaser />
      <Suspense fallback={<OverviewSkeleton />}>
        <Overview />
      </Suspense>
    </div>
  );
}

async function Overview() {
  let overview: MarketOverview;
  try {
    overview = await api.overview();
  } catch (error) {
    const apiError = toApiError(error);
    return <ErrorState message={apiError.message} retryable={apiError.retryable} />;
  }

  return (
    <div className="space-y-6">
      <AutoRefresh intervalMs={60_000} />
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
        {overview.as_of ? (
          <span>
            Snapshot updated <LocalTime iso={overview.as_of} />
          </span>
        ) : (
          <span>Fetching the first market snapshot…</span>
        )}
        <StaleBadge asOf={overview.as_of} stale={overview.stale} />
        {overview.pending_symbols > 0 && <span>· {overview.pending_symbols} instruments still loading</span>}
      </div>

      <LiveQuotesProvider symbols={overview.regions.flatMap((r) => r.indices.map((i) => i.symbol))}>
        <div className="grid gap-4 lg:grid-cols-2">
          {overview.regions.map((region) => (
            <Card key={region.region} title={region.region}>
              <div className="space-y-4">
                <IndexGrid indices={region.indices} />
                <MarketStatusList markets={region.markets} />
              </div>
            </Card>
          ))}
        </div>
      </LiveQuotesProvider>

      <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
        <Card title="Sector heatmap">
          <SectorHeatmap sectors={overview.sectors} />
        </Card>
        <Card title="Top movers">
          <div className="space-y-5">
            <MoversTable title="Gainers" movers={overview.gainers} />
            <MoversTable title="Losers" movers={overview.losers} />
            <p className="text-xs text-muted">Among {overview.movers_universe_size} large-cap US stocks we track.</p>
          </div>
        </Card>
      </div>
    </div>
  );
}

function OverviewSkeleton() {
  return (
    <div className="space-y-6" role="status" aria-label="Loading markets overview">
      <Skeleton className="h-4 w-48" />
      <div className="grid gap-4 lg:grid-cols-2">
        {Array.from({ length: 4 }, (_, i) => (
          <Card key={i}>
            <SkeletonBlock lines={5} label="Loading region" />
          </Card>
        ))}
      </div>
      <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
        <Card>
          <Skeleton className="h-40 w-full" />
        </Card>
        <Card>
          <SkeletonBlock lines={8} label="Loading movers" />
        </Card>
      </div>
    </div>
  );
}

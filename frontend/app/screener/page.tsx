import { connection } from "next/server";
import { Suspense } from "react";

import { ScreenerView } from "@/components/screener/ScreenerView";
import { AutoRefresh } from "@/components/ui/AutoRefresh";
import { Card, PageHeader, Skeleton, SkeletonBlock } from "@/components/ui/primitives";
import { ErrorState } from "@/components/ui/status";
import { cachedScreener, toSettled } from "@/lib/cached";

export const metadata = { title: "Screener" };

export default function ScreenerPage() {
  return (
    <div className="space-y-3">
      <PageHeader title="Screener">
        Filter and sort large-cap US stocks by price action, valuation, 52-week range and technical signal.
      </PageHeader>
      <Suspense fallback={<ScreenerSkeleton />}>
        <ScreenerLoader />
      </Suspense>
    </div>
  );
}

async function ScreenerLoader() {
  // Dynamic at the component level so the cache fills at request time, not during `next build`.
  await connection();
  const result = toSettled(await cachedScreener());
  if (result.error) {
    return <ErrorState message={result.error.message} retryable={result.error.retryable} />;
  }
  const screener = result.data;
  const warming = screener.refreshing || screener.pending_fundamentals > 0 || screener.quotes_as_of === null;
  return (
    <>
      {/* While the background job is still filling rows in, pick up its progress once a minute. */}
      {warming && <AutoRefresh intervalMs={60_000} />}
      <ScreenerView screener={screener} />
    </>
  );
}

function ScreenerSkeleton() {
  return (
    <div className="space-y-3" role="status" aria-label="Loading screener">
      <Skeleton className="h-4 w-56" />
      <Card>
        <Skeleton className="h-8 w-full" />
      </Card>
      <Card>
        <SkeletonBlock lines={14} label="Loading stocks" />
      </Card>
    </div>
  );
}

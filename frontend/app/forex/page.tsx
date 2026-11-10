import { connection } from "next/server";
import { Suspense } from "react";

import { ForexView } from "@/components/forex/ForexView";
import { PageHeader, SkeletonBlock } from "@/components/ui/primitives";
import { cachedForex } from "@/lib/cached";
import type { ForexBoard } from "@/types/api";

export const metadata = { title: "Forex & metals" };

/** Seeds ForexView with the server-cached board. On a cache miss/backend error it hands over undefined and
 *  ForexView fetches client-side as before. */
async function ForexBoardLoader() {
  // Dynamic at the component level so the cache fills at request time, not during `next build`.
  await connection();
  let initialBoard: ForexBoard | undefined;
  try {
    initialBoard = await cachedForex();
  } catch {
    initialBoard = undefined;
  }
  return <ForexView initialBoard={initialBoard} />;
}

export default function ForexPage() {
  return (
    <div className="space-y-3">
      <PageHeader title="Forex &amp; metals">
        Major currencies, Indian rupee pairs, gold and silver. Open any pair for its chart and signals.
      </PageHeader>
      <Suspense fallback={<SkeletonBlock lines={10} label="Loading forex rates" />}>
        <ForexBoardLoader />
      </Suspense>
    </div>
  );
}

import { Suspense } from "react";

import { CompareView } from "@/components/compare/CompareView";
import { PageHeader, SkeletonBlock } from "@/components/ui/primitives";

export const metadata = { title: "Compare" };

export default function ComparePage() {
  return (
    <div className="space-y-3">
      <PageHeader title="Compare">Chart up to four symbols against each other as percent change over the same period.</PageHeader>
      {/* CompareView reads ?symbols= (request-time), which needs a Suspense boundary under Cache Components. */}
      <Suspense fallback={<SkeletonBlock lines={8} label="Loading comparison" />}>
        <CompareView />
      </Suspense>
    </div>
  );
}

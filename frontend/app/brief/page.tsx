import { Suspense } from "react";

import { RequireAuth } from "@/components/auth/RequireAuth";
import { BriefView } from "@/components/signals/BriefView";
import { SkeletonBlock } from "@/components/ui/primitives";

export const metadata = { title: "Daily brief" };

export default function BriefPage({ searchParams }: PageProps<"/brief">) {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold text-primary">Daily Market Brief</h1>
      <RequireAuth what="daily brief">
        <Suspense fallback={<SkeletonBlock lines={8} label="Loading your brief" />}>
          <BriefForDate searchParams={searchParams} />
        </Suspense>
      </RequireAuth>
    </div>
  );
}

async function BriefForDate({ searchParams }: { searchParams: PageProps<"/brief">["searchParams"] }) {
  const raw = (await searchParams).date;
  const date = Array.isArray(raw) ? raw[0] : raw;
  return <BriefView date={date && /^\d{4}-\d{2}-\d{2}$/.test(date) ? date : null} />;
}

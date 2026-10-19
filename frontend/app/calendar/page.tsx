import { Suspense } from "react";

import { CalendarView } from "@/components/calendar/CalendarView";
import { SkeletonBlock } from "@/components/ui/primitives";

export const metadata = { title: "Earnings & IPO calendar" };

export default function CalendarPage({ searchParams }: PageProps<"/calendar">) {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-semibold text-primary">Earnings &amp; IPO calendar</h1>
        <p className="mt-1 text-sm text-secondary">Upcoming US earnings reports and IPOs, one week at a time.</p>
      </div>
      <Suspense fallback={<SkeletonBlock lines={8} label="Loading calendar" />}>
        <WithParams searchParams={searchParams} />
      </Suspense>
    </div>
  );
}

async function WithParams({ searchParams }: { searchParams: PageProps<"/calendar">["searchParams"] }) {
  const params = await searchParams;
  const tab = params.tab === "ipos" ? "ipos" : "earnings";
  const raw = Array.isArray(params.week) ? params.week[0] : params.week;
  // No ?week= means "the current week in the viewer's timezone", which only the browser can work out, so the
  // server never reads the clock here.
  const week = raw && /^\d{4}-\d{2}-\d{2}$/.test(raw) ? raw : null;
  return <CalendarView initialTab={tab} initialWeek={week} />;
}

import { connection } from "next/server";
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
  const week = raw && /^\d{4}-\d{2}-\d{2}$/.test(raw) ? raw : await currentWeekDate();
  return <CalendarView initialTab={tab} initialWeek={week} />;
}

/** Today's date (UTC, YYYY-MM-DD) as the default week. Reading the clock must wait for the request under
 * Cache Components, otherwise prerendering would bake in the build-time date. */
async function currentWeekDate(): Promise<string> {
  await connection();
  // eslint-disable-next-line no-restricted-syntax -- safe: runs at request time, after connection()
  return new Date().toISOString().slice(0, 10);
}

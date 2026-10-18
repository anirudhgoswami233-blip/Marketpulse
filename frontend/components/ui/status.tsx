"use client";

import { useRouter } from "next/navigation";
import { useTransition } from "react";

import { formatLocalDateTime, formatLocalTime } from "@/lib/format";
import { useHydrated } from "@/lib/hooks";

/**
 * Time in the viewer's timezone; renders a UTC fallback until hydrated to avoid a mismatch.
 * `withDate` adds the date when the instant isn't today (e.g. Friday's close seen on Sunday).
 */
export function LocalTime({ iso, withDate = false }: { iso: string; withDate?: boolean }) {
  const hydrated = useHydrated();
  if (!hydrated) {
    const utc = new Date(iso).toISOString();
    return (
      <time dateTime={iso}>
        {withDate ? `${utc.slice(0, 10)} ` : ""}
        {utc.slice(11, 16)} UTC
      </time>
    );
  }
  const isToday = new Date(iso).toDateString() === new Date().toDateString();
  return <time dateTime={iso}>{withDate && !isToday ? formatLocalDateTime(iso) : formatLocalTime(iso)}</time>;
}

/** "Data as of HH:MM" label, shown whenever we're serving cached data. */
export function StaleBadge({ asOf, stale }: { asOf: string | null; stale: boolean }) {
  if (!stale || !asOf) return null;
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full bg-surface-2 px-2 py-0.5 text-xs text-secondary"
      title="Live data is temporarily unavailable; showing the most recent cached data."
    >
      <span aria-hidden>⏱</span> Data as of <LocalTime iso={asOf} />
    </span>
  );
}

export function ErrorState({
  message,
  retryable = true,
  onRetry,
}: {
  message: string;
  retryable?: boolean;
  /** Defaults to re-rendering the current route's server components. */
  onRetry?: () => void;
}) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const retry = onRetry ?? (() => startTransition(() => router.refresh()));
  return (
    <div role="alert" className="rounded-lg border border-border bg-surface-2 px-4 py-5 text-sm">
      <p className="text-primary">{message}</p>
      {retryable && (
        <button
          type="button"
          onClick={retry}
          disabled={pending}
          className="mt-3 rounded-md border border-border px-3 py-1.5 text-xs font-medium text-primary hover:bg-surface disabled:opacity-60"
        >
          {pending ? "Retrying…" : "Try again"}
        </button>
      )}
    </div>
  );
}

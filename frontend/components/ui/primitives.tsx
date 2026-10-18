import type { ReactNode } from "react";

import { direction, formatChange, formatPct } from "@/lib/format";

export function Card({
  title,
  action,
  children,
  className = "",
}: {
  title?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-xl border border-border bg-surface p-4 sm:p-5 ${className}`}>
      {(title || action) && (
        <header className="mb-3 flex flex-wrap items-center justify-between gap-2">
          {title && <h2 className="text-sm font-semibold tracking-wide text-secondary uppercase">{title}</h2>}
          {action}
        </header>
      )}
      {children}
    </section>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div aria-hidden className={`animate-pulse rounded-md bg-surface-2 ${className}`} />;
}

/** A labelled loading placeholder: `lines` rows of skeleton bars. */
export function SkeletonBlock({ lines = 4, label = "Loading" }: { lines?: number; label?: string }) {
  return (
    <div role="status" aria-label={label} className="space-y-2">
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} className={`h-4 ${i % 3 === 2 ? "w-2/3" : "w-full"}`} />
      ))}
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-border px-4 py-8 text-center">
      <p className="font-medium text-primary">{title}</p>
      {children && <div className="mt-1 text-sm text-secondary">{children}</div>}
    </div>
  );
}

/** Gain/loss text: color plus arrow plus sign, so direction never relies on color alone. */
export function ChangeText({
  change,
  changePct,
  className = "",
}: {
  change?: string | null;
  changePct: string | null;
  className?: string;
}) {
  const dir = direction(changePct ?? change);
  const color = dir === "up" ? "text-up" : dir === "down" ? "text-down" : "text-secondary";
  const arrow = dir === "up" ? "▲" : dir === "down" ? "▼" : "";
  return (
    <span className={`tabular inline-flex items-center gap-1 ${color} ${className}`}>
      {arrow && <span aria-hidden>{arrow}</span>}
      {change !== undefined && <span>{formatChange(change)}</span>}
      <span>{change !== undefined ? `(${formatPct(changePct)})` : formatPct(changePct)}</span>
    </span>
  );
}

export function Pill({ tone, children }: { tone: "open" | "closed" | "neutral"; children: ReactNode }) {
  const styles = {
    open: "bg-up/15 text-up",
    closed: "bg-surface-2 text-secondary",
    neutral: "bg-surface-2 text-secondary",
  }[tone];
  return <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${styles}`}>{children}</span>;
}

import type { ReactNode } from "react";

import { direction, formatChange, formatPct } from "@/lib/format";

/** Page title with an optional one-line description and right-aligned action. */
export function PageHeader({ title, children, action }: { title: ReactNode; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-2">
      <div className="min-w-0">
        <h1 className="text-lg font-semibold text-primary">{title}</h1>
        {children && <p className="mt-0.5 max-w-3xl text-[13px] text-secondary">{children}</p>}
      </div>
      {action}
    </div>
  );
}

/**
 * A flat bordered panel with an optional header row. `flush` drops the body padding so a `.data-table`
 * or row list can run edge to edge.
 */
export function Card({
  title,
  action,
  children,
  className = "",
  flush = false,
}: {
  title?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  flush?: boolean;
}) {
  return (
    <section className={`min-w-0 rounded-md border border-border bg-surface ${className}`}>
      {(title || action) && (
        <header className="flex min-h-9 flex-wrap items-center justify-between gap-2 border-b border-border px-3 py-1.5">
          {title && <h2 className="section-label">{title}</h2>}
          {action}
        </header>
      )}
      <div className={flush ? "" : "p-3"}>{children}</div>
    </section>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div aria-hidden className={`skeleton ${className}`} />;
}

/** A labelled loading placeholder: `lines` rows of skeleton bars. */
export function SkeletonBlock({ lines = 4, label = "Loading" }: { lines?: number; label?: string }) {
  return (
    <div role="status" aria-label={label} className="space-y-2">
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} className={`h-3.5 ${i % 3 === 2 ? "w-2/3" : "w-full"}`} />
      ))}
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-sm border border-dashed border-border px-3 py-5 text-center">
      <p className="text-sm font-medium text-primary">{title}</p>
      {children && <div className="mt-0.5 text-[13px] text-secondary">{children}</div>}
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
    <span className={`tabular inline-flex items-baseline gap-1 whitespace-nowrap ${color} ${className}`}>
      {arrow && (
        <span aria-hidden className="text-[0.7em]">
          {arrow}
        </span>
      )}
      {change !== undefined && <span>{formatChange(change)}</span>}
      <span>{change !== undefined ? `(${formatPct(changePct)})` : formatPct(changePct)}</span>
    </span>
  );
}

/** Rectangular status label. `up`/`down` add the semantic color; the text always carries the meaning. */
export function Badge({ tone = "neutral", children }: { tone?: "up" | "down" | "neutral"; children: ReactNode }) {
  const styles = { up: "badge badge-up", down: "badge badge-down", neutral: "badge" }[tone];
  return <span className={styles}>{children}</span>;
}

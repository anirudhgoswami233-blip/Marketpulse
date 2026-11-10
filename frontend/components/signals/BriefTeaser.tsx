"use client";

import Link from "next/link";

import { SignalBadge } from "@/components/signals/SignalCard";
import { Skeleton } from "@/components/ui/primitives";
import { useAuth } from "@/lib/auth";
import { formatDate } from "@/lib/format";
import { useAuthedQuery } from "@/lib/useAuthedQuery";
import type { BriefStatus, SignalLabel } from "@/types/api";

const LABELS: SignalLabel[] = ["Bullish signals", "Bearish signals", "Neutral"];

/** A one-line pointer to the user's Daily Brief on the markets overview. */
export function BriefTeaser() {
  const { status } = useAuth();
  if (status === "loading") return <Skeleton className="h-9 w-full" />;
  if (status === "anonymous") {
    return (
      <p className="min-h-9 rounded-sm border border-border bg-surface px-3 py-2 text-[13px] text-secondary">
        The Daily Market Brief lists technical signals for the symbols on your watchlist each weekday.{" "}
        <Link href="/register?next=/brief" className="text-accent hover:underline">
          Create an account
        </Link>
      </p>
    );
  }
  return <SignedInTeaser />;
}

function SignedInTeaser() {
  const { state } = useAuthedQuery<BriefStatus>("/api/v1/brief");
  if (state.kind === "loading") return <Skeleton className="h-9 w-full" />;
  if (state.kind === "error") {
    return (
      <p role="status" className="min-h-9 rounded-sm border border-border bg-surface px-3 py-2 text-[13px] text-secondary">
        Your Daily Brief couldn&apos;t be loaded right now.{" "}
        <Link href="/brief" className="text-accent hover:underline">
          Open the brief
        </Link>
      </p>
    );
  }
  const brief = state.data.brief;
  return (
    <Link
      href="/brief"
      className="flex min-h-9 flex-wrap items-center gap-x-3 gap-y-1 rounded-sm border border-border bg-surface px-3 py-1.5 text-[13px] hover:bg-surface-2"
    >
      <span className="font-medium text-primary">Your Daily Brief</span>
      {brief ? (
        <>
          <span className="text-xs text-muted">{formatDate(brief.brief_date)}</span>
          {LABELS.map((label) => {
            const n = brief.items.filter((i) => i.signal.label === label).length;
            return n ? (
              <span key={label} className="inline-flex items-center gap-1 text-xs">
                <SignalBadge label={label} /> × {n}
              </span>
            ) : null;
          })}
        </>
      ) : (
        <span className="text-xs text-secondary">Not generated yet. Open to create one.</span>
      )}
      <span className="ml-auto text-xs font-medium text-accent">Open brief →</span>
    </Link>
  );
}

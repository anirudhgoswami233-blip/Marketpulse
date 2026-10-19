"use client";

import Link from "next/link";

import { SignalBadge } from "@/components/signals/SignalCard";
import { useAuth } from "@/lib/auth";
import { formatDate } from "@/lib/format";
import { useAuthedQuery } from "@/lib/useAuthedQuery";
import type { BriefStatus, SignalLabel } from "@/types/api";

const LABELS: SignalLabel[] = ["Bullish signals", "Bearish signals", "Neutral"];

/** A one-line pointer to the user's Daily Brief on the markets overview. */
export function BriefTeaser() {
  const { status } = useAuth();
  if (status === "loading") return null;
  if (status === "anonymous") {
    return (
      <p className="rounded-lg border border-dashed border-border px-4 py-3 text-sm text-secondary">
        Get a personalised Daily Market Brief built from technical signals on your watchlist.{" "}
        <Link href="/register?next=/brief" className="text-accent hover:underline">
          Create a free account
        </Link>
      </p>
    );
  }
  return <SignedInTeaser />;
}

function SignedInTeaser() {
  const { state } = useAuthedQuery<BriefStatus>("/api/v1/brief");
  if (state.kind !== "ready") return null;
  const brief = state.data.brief;
  return (
    <Link
      href="/brief"
      className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-border bg-surface px-4 py-3 text-sm hover:bg-surface-2"
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
      <span className="ml-auto text-xs text-accent">Read →</span>
    </Link>
  );
}

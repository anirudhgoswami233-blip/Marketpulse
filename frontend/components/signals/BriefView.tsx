"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Disclaimer, SignalBadge, SignalCard } from "@/components/signals/SignalCard";
import { Card, EmptyState, SkeletonBlock } from "@/components/ui/primitives";
import { ErrorState, LocalTime } from "@/components/ui/status";
import { toApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDate, formatPct } from "@/lib/format";
import { useAuthedQuery } from "@/lib/useAuthedQuery";
import type { Brief, BriefStatus, BriefSummary, SignalLabel, User } from "@/types/api";

const POLL_MS = 3000;
const LABEL_ORDER: SignalLabel[] = ["Bullish signals", "Bearish signals", "Neutral"];

export function BriefView({ date }: { date: string | null }) {
  const status = useAuthedQuery<BriefStatus>("/api/v1/brief");
  const older = useAuthedQuery<Brief>(date ? `/api/v1/briefs/${date}` : null);
  const history = useAuthedQuery<BriefSummary[]>("/api/v1/briefs");
  const { authRequest } = useAuth();
  const [startError, setStartError] = useState<string | null>(null);

  const generating = status.state.kind === "ready" && status.state.data.generating;
  const { reload: reloadStatus } = status;
  const { reload: reloadHistory } = history;
  // While a brief is being generated, poll until it's done.
  useEffect(() => {
    if (!generating) return;
    const id = window.setInterval(() => {
      reloadStatus();
      reloadHistory();
    }, POLL_MS);
    return () => window.clearInterval(id);
  }, [generating, reloadStatus, reloadHistory]);

  const generate = async () => {
    setStartError(null);
    try {
      await authRequest<void>("/api/v1/brief/generate", { method: "POST" });
      reloadStatus();
    } catch (error) {
      setStartError(toApiError(error).message);
    }
  };

  if (status.state.kind === "loading") return <SkeletonBlock lines={10} label="Loading your brief" />;
  if (status.state.kind === "error") {
    const e = status.state.error;
    return <ErrorState message={e.message} retryable={e.retryable} onRetry={status.reload} />;
  }
  const { data } = status.state;
  const showing = date ? (older.state.kind === "ready" ? older.state.data : null) : data.brief;

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_18rem]">
      <div className="min-w-0 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-sm text-secondary">
            {data.next_scheduled_at ? (
              <>
                Your next brief is scheduled for <LocalTime iso={data.next_scheduled_at} />. Briefs run on weekdays.
              </>
            ) : (
              "Briefs run on weekday mornings in your timezone."
            )}
          </p>
          <button
            type="button"
            onClick={generate}
            disabled={generating}
            className="rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-surface hover:opacity-90 disabled:opacity-60"
          >
            {generating ? "Generating…" : "Generate now"}
          </button>
        </div>
        {startError && (
          <p role="alert" className="text-sm text-down">
            {startError}
          </p>
        )}
        {generating && (
          <p role="status" className="rounded-md bg-surface-2 px-3 py-2 text-sm text-secondary">
            Building your brief. Signals are computed one symbol at a time to stay within data-provider limits, so this
            can take a few minutes for a long watchlist.
          </p>
        )}
        {date && older.state.kind === "loading" && <SkeletonBlock lines={8} label="Loading brief" />}
        {date && older.state.kind === "error" && (
          <ErrorState message={older.state.error.message} retryable={older.state.error.retryable} onRetry={older.reload} />
        )}
        {showing ? (
          <BriefContent brief={showing} />
        ) : (
          !date &&
          !generating && (
            <EmptyState title="No brief yet">
              Your first brief arrives at your scheduled time on the next weekday, or generate one now. Add symbols to a{" "}
              <Link href="/watchlists" className="text-accent hover:underline">
                watchlist
              </Link>{" "}
              to include them.
            </EmptyState>
          )
        )}
      </div>
      <aside className="space-y-4">
        <BriefSettings emailAvailable={data.email_available} onSaved={status.reload} />
        <Card title="Past briefs">
          {history.state.kind === "ready" && history.state.data.length > 0 ? (
            <ul className="space-y-1 text-sm">
              {history.state.data.map((b) => (
                <li key={b.brief_date}>
                  <Link href={`/brief?date=${b.brief_date}`} className="text-accent hover:underline">
                    {formatDate(b.brief_date)}
                  </Link>{" "}
                  <span className="text-xs text-muted">({b.signal_count} signals)</span>
                </li>
              ))}
            </ul>
          ) : history.state.kind === "loading" ? (
            <SkeletonBlock lines={3} label="Loading past briefs" />
          ) : (
            <p className="text-sm text-muted">None yet.</p>
          )}
        </Card>
      </aside>
    </div>
  );
}

function BriefContent({ brief }: { brief: Brief }) {
  const groups = (["watchlist", "trending"] as const).map((source) => ({
    source,
    items: brief.items.filter((i) => i.source === source),
  }));
  const counts = LABEL_ORDER.map((label) => ({ label, n: brief.items.filter((i) => i.signal.label === label).length }));
  return (
    <div className="space-y-4">
      <Card title={`Brief for ${formatDate(brief.brief_date)}`}>
        <p className="mb-3 text-xs text-muted">
          Generated <LocalTime iso={brief.generated_at} withDate />
          {brief.emailed_at && " · emailed"}
        </p>
        <div className="mb-3 flex flex-wrap gap-2">
          {counts.map(({ label, n }) => (
            <span key={label} className="inline-flex items-center gap-1 text-xs text-secondary">
              <SignalBadge label={label} /> × {n}
            </span>
          ))}
        </div>
        <h3 className="mb-2 text-sm font-medium text-primary">Overnight (regional ETF proxies)</h3>
        <ul className="grid gap-2 sm:grid-cols-2">
          {brief.overnight.regions.map((r) => (
            <li key={r.region} className="rounded-lg border border-border px-3 py-2 text-sm">
              <div className="flex justify-between gap-2">
                <span className="font-medium text-primary">{r.region}</span>
                <span className="tabular text-secondary">{r.avg_change_pct === null ? "n/a" : formatPct(r.avg_change_pct)}</span>
              </div>
              <p className="mt-1 text-xs text-muted">{r.detail.join(", ") || "No data"}</p>
            </li>
          ))}
        </ul>
        {brief.overnight.unavailable && brief.overnight.unavailable.length > 0 && (
          <p className="mt-3 text-xs text-muted">
            Signals couldn&apos;t be computed for: {brief.overnight.unavailable.join(", ")}.
          </p>
        )}
      </Card>
      {groups.map(({ source, items }) => (
        <Card key={source} title={source === "watchlist" ? "Your watchlist" : "Trending today"}>
          {items.length === 0 ? (
            <EmptyState title={source === "watchlist" ? "No watchlist symbols in this brief" : "No trending symbols"}>
              {source === "watchlist" && (
                <Link href="/watchlists" className="text-accent hover:underline">
                  Add symbols to a watchlist
                </Link>
              )}
            </EmptyState>
          ) : (
            <ul className="divide-y divide-border">
              {items.map(({ signal }) => (
                <li key={signal.id} className="py-3">
                  <SignalCard signal={signal} showSymbol compact showDisclaimer={false} />
                </li>
              ))}
            </ul>
          )}
        </Card>
      ))}
      <Disclaimer />
    </div>
  );
}

const TIMEZONES: string[] =
  typeof Intl.supportedValuesOf === "function" ? Intl.supportedValuesOf("timeZone") : ["UTC"];

function BriefSettings({ emailAvailable, onSaved }: { emailAvailable: boolean; onSaved: () => void }) {
  const { user, authRequest, updateUser } = useAuth();
  const [message, setMessage] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const [saving, setSaving] = useState(false);
  if (!user) return null;

  const save = async (form: FormData) => {
    setSaving(true);
    setMessage(null);
    try {
      const updated = await authRequest<User>("/api/v1/auth/me", {
        method: "PATCH",
        json: {
          brief_time: String(form.get("brief_time")),
          timezone: String(form.get("timezone")),
          brief_email_enabled: form.get("brief_email_enabled") === "on",
        },
      });
      updateUser(updated);
      setMessage({ tone: "ok", text: "Saved." });
      onSaved();
    } catch (error) {
      setMessage({ tone: "error", text: toApiError(error).message });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card title="Brief settings">
      <form action={save} className="space-y-3 text-sm">
        <label className="block space-y-1">
          <span className="text-secondary">Time (your timezone)</span>
          <input
            type="time"
            name="brief_time"
            defaultValue={user.brief_time.slice(0, 5)}
            required
            className="w-full rounded-md border border-border bg-surface px-2 py-1.5 text-primary"
          />
        </label>
        <label className="block space-y-1">
          <span className="text-secondary">Timezone</span>
          <select
            name="timezone"
            defaultValue={user.timezone}
            className="w-full rounded-md border border-border bg-surface px-2 py-1.5 text-primary"
          >
            {(TIMEZONES.includes(user.timezone) ? TIMEZONES : [user.timezone, ...TIMEZONES]).map((tz) => (
              <option key={tz} value={tz}>
                {tz}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-start gap-2">
          <input
            type="checkbox"
            name="brief_email_enabled"
            defaultChecked={user.brief_email_enabled}
            disabled={!emailAvailable}
            className="mt-0.5"
          />
          <span className="text-secondary">
            Email me the brief
            {!emailAvailable && <span className="block text-xs text-muted">Email isn&apos;t set up on this server yet.</span>}
          </span>
        </label>
        <button
          type="submit"
          disabled={saving}
          className="w-full rounded-md border border-border py-1.5 text-xs font-medium text-primary hover:bg-surface-2 disabled:opacity-60"
        >
          {saving ? "Saving…" : "Save settings"}
        </button>
        {message && (
          <p role={message.tone === "error" ? "alert" : "status"} className={`text-xs ${message.tone === "ok" ? "text-up" : "text-down"}`}>
            {message.text}
          </p>
        )}
      </form>
    </Card>
  );
}

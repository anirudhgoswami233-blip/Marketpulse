import Link from "next/link";

import { formatDate, formatPct } from "@/lib/format";
import type { Signal, SignalLabel, SignalReason } from "@/types/api";

export const DISCLAIMER = "Educational information based on technical indicators, not financial advice.";

const LABEL_STYLE: Record<SignalLabel, { icon: string; className: string }> = {
  "Bullish signals": { icon: "▲", className: "bg-up/15 text-up" },
  "Bearish signals": { icon: "▼", className: "bg-down/15 text-down" },
  Neutral: { icon: "●", className: "bg-surface-2 text-secondary" },
};

/** Label badge: icon + words, so the meaning never depends on colour alone. */
export function SignalBadge({ label, score }: { label: SignalLabel; score?: number }) {
  const style = LABEL_STYLE[label];
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${style.className}`}>
      <span aria-hidden>{style.icon}</span>
      {label}
      {score !== undefined && <span className="tabular opacity-80">({score > 0 ? "+" : ""}{score})</span>}
    </span>
  );
}

function ReasonIcon({ reason }: { reason: SignalReason }) {
  if (reason.direction > 0) return <span className="text-up" aria-label="bullish reading">▲</span>;
  if (reason.direction < 0) return <span className="text-down" aria-label="bearish reading">▼</span>;
  return <span className="text-muted" aria-label="neutral reading">●</span>;
}

/** Score on a -100..+100 track; a text value sits beside it for screen readers and precision. */
export function ScoreBar({ score }: { score: number }) {
  const clamped = Math.max(-100, Math.min(100, score));
  const left = clamped < 0 ? 50 + clamped / 2 : 50;
  const width = Math.abs(clamped) / 2;
  return (
    <div className="flex items-center gap-2" aria-hidden>
      <span className="text-[10px] text-muted">−100</span>
      <div className="relative h-1.5 flex-1 rounded-full bg-surface-2">
        <div className="absolute top-0 h-full w-px bg-border" style={{ left: "50%" }} />
        <div
          className={`absolute top-0 h-full rounded-full ${clamped >= 0 ? "bg-up" : "bg-down"}`}
          style={{ left: `${left}%`, width: `${width}%` }}
        />
      </div>
      <span className="text-[10px] text-muted">+100</span>
    </div>
  );
}

export function SignalCard({
  signal,
  showSymbol = false,
  compact = false,
  showDisclaimer = true,
}: {
  signal: Signal;
  showSymbol?: boolean;
  compact?: boolean;
  showDisclaimer?: boolean;
}) {
  return (
    <article className="space-y-3" aria-label={`${signal.display_symbol}: ${signal.label}, score ${signal.score}`}>
      <header className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          {showSymbol && (
            <Link href={`/stock/${encodeURIComponent(signal.symbol)}`} className="font-semibold text-primary hover:text-accent">
              {signal.display_symbol}
              <span className="ml-1 text-xs font-normal text-secondary">{signal.description}</span>
            </Link>
          )}
          <SignalBadge label={signal.label} score={signal.score} />
        </div>
        <span className="text-xs text-muted">Based on the close of {formatDate(signal.signal_date)}</span>
      </header>
      {!compact && <ScoreBar score={signal.score} />}
      {signal.reasons.length > 0 ? (
        <ul className="space-y-1 text-sm">
          {signal.reasons.map((reason) => (
            <li key={reason.rule} className="flex gap-2">
              <ReasonIcon reason={reason} />
              <span className="text-primary">{reason.reason}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-secondary">Not enough data to read any indicator yet.</p>
      )}
      {!compact && signal.skipped.length > 0 && (
        <details className="text-xs text-muted">
          <summary className="cursor-pointer">Not evaluated ({signal.skipped.length})</summary>
          <ul className="mt-1 list-disc space-y-0.5 pl-4">
            {signal.skipped.map((s) => (
              <li key={s.rule}>{s.reason}</li>
            ))}
          </ul>
        </details>
      )}
      {!compact && signal.outcomes.length > 0 && (
        <p className="text-xs text-secondary">
          Since then:{" "}
          {signal.outcomes.map((o) => `${o.horizon_days}d ${formatPct(o.return_pct)}`).join(" · ")}
        </p>
      )}
      {showDisclaimer && <Disclaimer />}
    </article>
  );
}

export function Disclaimer() {
  return <p className="text-xs text-muted italic">{DISCLAIMER}</p>;
}

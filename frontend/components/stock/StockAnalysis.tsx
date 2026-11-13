import Link from "next/link";

import { ChangeText, EmptyState } from "@/components/ui/primitives";
import { direction, formatDate, formatPrice } from "@/lib/format";
import type { EarningsSurprise, Peer, RecommendationTrend } from "@/types/api";

const RATINGS = [
  { key: "strong_buy", label: "Strong buy", background: "var(--div-up-4)" },
  { key: "buy", label: "Buy", background: "var(--div-up-2)" },
  { key: "hold", label: "Hold", background: "var(--div-mid)" },
  { key: "sell", label: "Sell", background: "var(--div-down-2)" },
  { key: "strong_sell", label: "Strong sell", background: "var(--div-down-4)" },
] as const;

export function ratingTotal(trend: RecommendationTrend): number {
  return RATINGS.reduce((sum, r) => sum + trend[r.key], 0);
}

/** The analysts' average rating as words. Weights: strong buy +2 … strong sell −2. */
export function consensusLabel(trend: RecommendationTrend): string | null {
  const total = ratingTotal(trend);
  if (total === 0) return null;
  const score = (2 * trend.strong_buy + trend.buy - trend.sell - 2 * trend.strong_sell) / total;
  if (score >= 1.25) return "Strong buy";
  if (score >= 0.5) return "Buy";
  if (score > -0.5) return "Hold";
  if (score > -1.25) return "Sell";
  return "Strong sell";
}

function monthLabel(isoDate: string): string {
  return new Intl.DateTimeFormat(undefined, { month: "short", year: "numeric", timeZone: "UTC" }).format(new Date(isoDate));
}

/** Analyst rating distribution for the latest month, plus how it moved over the previous months. */
export function AnalystRatings({ trends }: { trends: RecommendationTrend[] }) {
  const latest = trends[0];
  const total = latest ? ratingTotal(latest) : 0;
  if (!latest || total === 0) return <EmptyState title="No analyst coverage for this symbol" />;
  const consensus = consensusLabel(latest);

  return (
    <div className="space-y-3">
      <div>
        <p className="text-sm text-primary">
          Consensus: <span className="font-semibold">{consensus}</span>
        </p>
        <p className="tabular text-xs text-muted">
          {total} analysts · {monthLabel(latest.period)}
        </p>
      </div>

      {/* The bar is decoration for the counts listed underneath; 2px gaps keep neighbours distinct. */}
      <div className="flex h-2.5 gap-0.5" aria-hidden>
        {RATINGS.filter((r) => latest[r.key] > 0).map((r) => (
          <div key={r.key} style={{ background: r.background, width: `${(latest[r.key] / total) * 100}%` }} />
        ))}
      </div>
      <ul className="tabular flex flex-wrap gap-x-3 gap-y-1 text-xs text-secondary">
        {RATINGS.map((r) => (
          <li key={r.key} className="inline-flex items-center gap-1">
            <span aria-hidden className="inline-block h-2 w-2" style={{ background: r.background }} />
            {r.label} <span className="font-medium text-primary">{latest[r.key]}</span>
          </li>
        ))}
      </ul>

      {trends.length > 1 && (
        <div className="-mx-3 overflow-x-auto border-t border-border">
          <table className="data-table">
            <caption className="sr-only">Analyst ratings by month</caption>
            <thead>
              <tr>
                <th scope="col">Month</th>
                {RATINGS.map((r) => (
                  <th key={r.key} scope="col" className="num">
                    {r.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {trends.map((t) => (
                <tr key={t.period}>
                  <td className="whitespace-nowrap">{monthLabel(t.period)}</td>
                  {RATINGS.map((r) => (
                    <td key={r.key} className="num">
                      {t[r.key]}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="text-xs text-muted">Ratings published by brokerage analysts, shown as reported. Not a recommendation.</p>
    </div>
  );
}

function outcome(q: EarningsSurprise): string {
  const dir = direction(q.surprise ?? q.surprise_pct);
  return dir === "up" ? "Beat" : dir === "down" ? "Missed" : "In line";
}

/** Reported EPS against the consensus estimate, newest quarter first. */
export function EarningsHistory({ quarters, currency }: { quarters: EarningsSurprise[]; currency: string | null }) {
  if (quarters.length === 0) return <EmptyState title="No earnings history for this symbol" />;
  return (
    <div className="overflow-x-auto">
      <table className="data-table min-w-[28rem]">
        <caption className="sr-only">Earnings per share: actual against estimate, by quarter</caption>
        <thead>
          <tr>
            <th scope="col">Quarter</th>
            <th scope="col">Period end</th>
            <th scope="col" className="num">
              EPS est.
            </th>
            <th scope="col" className="num">
              EPS actual
            </th>
            <th scope="col" className="num">
              Surprise
            </th>
          </tr>
        </thead>
        <tbody>
          {quarters.map((q) => (
            <tr key={q.period}>
              <td className="font-medium whitespace-nowrap">{q.quarter && q.year ? `Q${q.quarter} ${q.year}` : "—"}</td>
              <td className="text-xs whitespace-nowrap text-secondary">{formatDate(q.period)}</td>
              <td className="num">{formatPrice(q.eps_estimate, currency)}</td>
              <td className="num text-primary">{formatPrice(q.eps_actual, currency)}</td>
              <td className="num">
                {q.eps_actual === null || q.surprise_pct === null ? (
                  <span className="text-muted">—</span>
                ) : (
                  <span className="inline-flex items-baseline gap-1.5">
                    <span className="text-xs text-secondary">{outcome(q)}</span>
                    <ChangeText changePct={q.surprise_pct} />
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Companies in the same industry, each linking to its page, with a shortcut to chart them together. */
export function PeersList({ symbol, peers }: { symbol: string; peers: Peer[] }) {
  if (peers.length === 0) return <EmptyState title="No peers found for this symbol" />;
  const compare = [symbol, ...peers.slice(0, 3).map((p) => p.symbol)].map(encodeURIComponent).join(",");
  return (
    <div>
      <ul className="divide-y divide-border">
        {peers.map((p) => (
          <li key={p.symbol}>
            <Link
              href={`/stock/${encodeURIComponent(p.symbol)}`}
              className="flex items-baseline justify-between gap-3 px-3 py-1.5 text-[13px] hover:bg-surface-2"
            >
              <span className="font-medium text-primary">{p.display_symbol}</span>
              <span className="truncate text-xs text-muted">{p.description}</span>
            </Link>
          </li>
        ))}
      </ul>
      <p className="border-t border-border px-3 py-2">
        <Link href={`/compare?symbols=${compare}`} className="text-xs font-medium text-accent hover:underline">
          Compare performance →
        </Link>
      </p>
    </div>
  );
}

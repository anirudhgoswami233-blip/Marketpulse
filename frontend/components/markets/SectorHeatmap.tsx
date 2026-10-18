import Link from "next/link";

import { EmptyState } from "@/components/ui/primitives";
import { formatPct } from "@/lib/format";
import type { SectorTile } from "@/types/api";

// Diverging scale: four steps per arm around a neutral gray. Thresholds are % daily change.
const STEPS = [0.25, 1, 2, 3];

export function heatColor(changePct: number | null): { background: string; color: string } {
  if (changePct === null || Math.abs(changePct) < STEPS[0]) {
    return { background: "var(--div-mid)", color: "var(--on-div-soft)" };
  }
  const magnitude = Math.abs(changePct);
  const step = magnitude >= STEPS[3] ? 4 : magnitude >= STEPS[2] ? 3 : magnitude >= STEPS[1] ? 2 : 1;
  const arm = changePct > 0 ? "up" : "down";
  // Text contrast (checked per theme): steps 1-2 take soft ink, steps 3-4 strong ink; tokens flip in dark mode.
  const color = step >= 3 ? "var(--on-div-strong)" : "var(--on-div-soft)";
  return { background: `var(--div-${arm}-${step})`, color };
}

export function SectorHeatmap({ sectors }: { sectors: SectorTile[] }) {
  const priced = sectors.filter((s) => s.change_pct !== null);
  if (priced.length === 0) {
    return <EmptyState title="Sector data is loading">Prices appear once the first market snapshot finishes.</EmptyState>;
  }
  const sorted = [...sectors].sort((a, b) => Number(b.change_pct ?? -Infinity) - Number(a.change_pct ?? -Infinity));
  return (
    <div>
      <ul className="grid grid-cols-2 gap-0.5 sm:grid-cols-3 lg:grid-cols-4" aria-label="Sector performance today">
        {sorted.map((s) => {
          const pct = s.change_pct === null ? null : Number(s.change_pct);
          const style = heatColor(pct);
          const arrow = pct === null || pct === 0 ? "" : pct > 0 ? "▲" : "▼";
          return (
            <li key={s.symbol}>
              <Link
                href={`/stock/${s.symbol}`}
                style={style}
                className="flex h-16 flex-col justify-between rounded-sm p-2 text-sm outline-offset-2 hover:ring-2 hover:ring-accent"
                title={`${s.sector} (${s.symbol}): ${formatPct(s.change_pct)} today`}
              >
                <span className="truncate font-medium">{s.sector}</span>
                <span className="tabular font-semibold">
                  {arrow && <span aria-hidden>{arrow} </span>}
                  {pct === null ? "—" : formatPct(pct)}
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
      <p className="mt-2 flex flex-wrap items-center gap-3 text-xs text-muted">
        <span className="inline-flex items-center gap-1">
          <span aria-hidden className="inline-block h-3 w-3 rounded-sm" style={{ background: "var(--div-up-3)" }} />
          gain
        </span>
        <span className="inline-flex items-center gap-1">
          <span aria-hidden className="inline-block h-3 w-3 rounded-sm" style={{ background: "var(--div-mid)" }} />
          ±0.25%
        </span>
        <span className="inline-flex items-center gap-1">
          <span aria-hidden className="inline-block h-3 w-3 rounded-sm" style={{ background: "var(--div-down-3)" }} />
          loss
        </span>
        <span>SPDR sector ETFs, daily change</span>
      </p>
    </div>
  );
}

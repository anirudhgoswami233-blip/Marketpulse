"use client";

import dynamic from "next/dynamic";

import { Skeleton } from "@/components/ui/primitives";
import { formatDate } from "@/lib/format";

export interface LinePoint {
  date: string; // YYYY-MM-DD
  value: number;
}

/** Same footprint as the canvas (hover line + 140px plot), so swapping it in doesn't shift the page. */
function CanvasSkeleton() {
  return (
    <div role="status" aria-label="Loading chart">
      <div className="h-4" />
      <Skeleton className="h-[140px] w-full" />
    </div>
  );
}

const MiniLineCanvas = dynamic(() => import("@/components/macro/MiniLineCanvas"), { ssr: false, loading: CanvasSkeleton });

/**
 * One series on one axis (the card title names it, so no legend). Hover shows the date and value; a data
 * table sits behind a disclosure for screen readers and exact values.
 */
export function MiniLineChart({ points, unit, label }: { points: LinePoint[]; unit: string; label: string }) {
  return (
    <div>
      <MiniLineCanvas points={points} unit={unit} label={label} />
      <details className="mt-1 text-xs text-secondary">
        <summary className="cursor-pointer">Data table</summary>
        <table className="data-table mt-1">
          <caption className="sr-only">{label}, most recent first</caption>
          <tbody>
            {points
              .slice(-24)
              .reverse()
              .map((p) => (
                <tr key={p.date}>
                  <td>{formatDate(p.date)}</td>
                  <td className="num">{p.value.toFixed(2)}</td>
                </tr>
              ))}
          </tbody>
        </table>
      </details>
    </div>
  );
}

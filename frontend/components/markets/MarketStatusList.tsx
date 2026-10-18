"use client";

import { Pill } from "@/components/ui/primitives";
import { formatCountdown, formatTimeIn } from "@/lib/format";
import { useNow } from "@/lib/hooks";
import type { MarketStatus } from "@/types/api";

const SESSION_LABEL: Record<MarketStatus["session"], string> = {
  pre_market: "Pre-market",
  regular: "Open",
  post_market: "After hours",
  closed: "Closed",
};

export function MarketStatusList({ markets }: { markets: MarketStatus[] }) {
  const now = useNow(30_000);
  return (
    <ul className="divide-y divide-border">
      {markets.map((m) => {
        // Local exchange time keeps ticking on the client; before hydration show the server's snapshot.
        const localIso = now ? new Date(now).toISOString() : m.local_time;
        const label = m.holiday ? `Holiday: ${m.holiday}` : SESSION_LABEL[m.is_open ? "regular" : m.session];
        return (
          <li key={m.exchange} className="flex items-center justify-between gap-3 py-2 text-sm">
            <div className="min-w-0">
              <p className="truncate font-medium text-primary" title={m.name}>
                {m.name}
              </p>
              <p className="tabular text-xs text-muted">
                {formatTimeIn(localIso, m.timezone)} local
                {m.next_change_at && now && (
                  <> · {m.is_open ? "closes" : "opens"} {formatCountdown(m.next_change_at, now)}</>
                )}
                {m.status_source === "schedule" && " · regular hours"}
              </p>
            </div>
            <Pill tone={m.is_open ? "open" : "closed"}>
              <span aria-hidden>{m.is_open ? "●" : "○"}</span>
              {label}
            </Pill>
          </li>
        );
      })}
    </ul>
  );
}

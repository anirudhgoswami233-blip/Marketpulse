"use client";

import { Badge } from "@/components/ui/primitives";
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
    <ul className="divide-y divide-border border-t border-border">
      {markets.map((m) => {
        // Local exchange time keeps ticking on the client; before hydration show the server's snapshot.
        const localIso = now ? new Date(now).toISOString() : m.local_time;
        const label = m.holiday ? `Holiday: ${m.holiday}` : SESSION_LABEL[m.is_open ? "regular" : m.session];
        return (
          <li key={m.exchange} className="flex items-center justify-between gap-3 px-3 py-1.5">
            <div className="min-w-0">
              <p className="truncate text-[13px] text-primary" title={m.name}>
                {m.name}
              </p>
              <p className="tabular truncate text-2xs text-muted">
                {formatTimeIn(localIso, m.timezone)} local
                {m.next_change_at && now && (
                  <> · {m.is_open ? "closes" : "opens"} {formatCountdown(m.next_change_at, now)}</>
                )}
                {m.status_source === "schedule" && " · regular hours"}
              </p>
            </div>
            <Badge tone={m.is_open ? "up" : "neutral"}>
              <span aria-hidden className="text-[0.7em]">
                {m.is_open ? "●" : "○"}
              </span>
              {label}
            </Badge>
          </li>
        );
      })}
    </ul>
  );
}

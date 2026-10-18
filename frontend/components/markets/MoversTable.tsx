import Link from "next/link";

import { ChangeText, EmptyState } from "@/components/ui/primitives";
import { formatPrice } from "@/lib/format";
import type { Mover } from "@/types/api";

export function MoversTable({ title, movers }: { title: string; movers: Mover[] }) {
  return (
    <div>
      <h3 className="mb-2 text-sm font-medium text-primary">{title}</h3>
      {movers.length === 0 ? (
        <EmptyState title={`No ${title.toLowerCase()} right now`} />
      ) : (
        <table className="w-full text-sm">
          <caption className="sr-only">{title}</caption>
          <thead>
            <tr className="text-left text-xs text-muted">
              <th scope="col" className="pb-1 font-normal">
                Symbol
              </th>
              <th scope="col" className="pb-1 text-right font-normal">
                Price
              </th>
              <th scope="col" className="pb-1 text-right font-normal">
                Change
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {movers.map((m) => (
              <tr key={m.symbol}>
                <td className="py-1.5">
                  <Link href={`/stock/${encodeURIComponent(m.symbol)}`} className="font-medium text-primary hover:text-accent">
                    {m.symbol}
                  </Link>
                </td>
                <td className="tabular py-1.5 text-right text-primary">{formatPrice(m.price, m.currency ?? "USD")}</td>
                <td className="py-1.5 text-right">
                  <ChangeText changePct={m.change_pct} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

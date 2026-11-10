import Link from "next/link";

import { ChangeText, EmptyState } from "@/components/ui/primitives";
import { formatPrice } from "@/lib/format";
import type { Mover } from "@/types/api";

export function MoversTable({ title, movers }: { title: string; movers: Mover[] }) {
  if (movers.length === 0) {
    return (
      <div className="p-3">
        <EmptyState title={`No ${title.toLowerCase()} right now`} />
      </div>
    );
  }
  return (
    <table className="data-table">
      <caption className="sr-only">{title}</caption>
      <thead>
        <tr>
          <th scope="col">{title}</th>
          <th scope="col" className="num">
            Price
          </th>
          <th scope="col" className="num">
            Change
          </th>
        </tr>
      </thead>
      <tbody>
        {movers.map((m) => (
          <tr key={m.symbol}>
            <td>
              <Link href={`/stock/${encodeURIComponent(m.symbol)}`} className="font-medium text-primary hover:text-accent">
                {m.symbol}
              </Link>
            </td>
            <td className="num text-primary">{formatPrice(m.price, m.currency ?? "USD")}</td>
            <td className="num">
              <ChangeText changePct={m.change_pct} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

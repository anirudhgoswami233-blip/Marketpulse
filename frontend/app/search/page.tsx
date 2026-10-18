import Link from "next/link";
import { Suspense } from "react";

import { SearchBox } from "@/components/search/SearchBox";
import { Card, EmptyState, SkeletonBlock } from "@/components/ui/primitives";
import { ErrorState } from "@/components/ui/status";
import { api, toApiError } from "@/lib/api";
import type { SearchResults } from "@/types/api";

export const metadata = { title: "Search" };

export default function SearchPage({ searchParams }: PageProps<"/search">) {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold text-primary">Search</h1>
      <SearchBox autoFocus />
      <Suspense fallback={<SkeletonBlock lines={8} label="Searching" />}>
        <Results searchParams={searchParams} />
      </Suspense>
    </div>
  );
}

async function Results({ searchParams }: { searchParams: PageProps<"/search">["searchParams"] }) {
  const raw = (await searchParams).q;
  const q = (Array.isArray(raw) ? raw[0] : raw)?.trim() ?? "";
  if (!q) {
    return <EmptyState title="Search for a stock, ETF or forex pair">Try “Apple”, “SPY” or “EUR/USD”.</EmptyState>;
  }

  let data: SearchResults;
  try {
    data = await api.search(q, 50);
  } catch (error) {
    const apiError = toApiError(error);
    return <ErrorState message={apiError.message} retryable={apiError.retryable} />;
  }
  if (data.results.length === 0) {
    return <EmptyState title={`No matches for “${q}”`}>Check the spelling or search by ticker.</EmptyState>;
  }
  return (
    <Card title={`${data.results.length} results for “${q}”`}>
      <ul className="divide-y divide-border">
        {data.results.map((r) => (
          <li key={`${r.symbol}-${r.exchange}`}>
            <Link
              href={`/stock/${encodeURIComponent(r.symbol)}`}
              className="flex items-center justify-between gap-3 py-2 text-sm hover:text-accent"
            >
              <span className="min-w-0">
                <span className="font-semibold text-primary">{r.display_symbol}</span>{" "}
                <span className="text-secondary">{r.description}</span>
              </span>
              <span className="shrink-0 text-xs text-muted">
                {r.exchange} · {r.type || "—"}
                {!r.price_available && " · profile only"}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </Card>
  );
}

import { EmptyState } from "@/components/ui/primitives";
import { formatCompact, formatDate, formatNumber, formatPct, formatPrice } from "@/lib/format";
import type { CompanyProfile, KeyMetrics, NewsItem, Quote } from "@/types/api";

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="kv-row">
      <dt className="text-secondary">{label}</dt>
      <dd className="tabular text-right text-primary">{value}</dd>
    </div>
  );
}

export function KeyStats({
  quote,
  metrics,
  currency,
}: {
  quote: Quote | null;
  metrics: KeyMetrics | null;
  currency: string | null;
}) {
  if (!quote && !metrics) return <EmptyState title="No key statistics available" />;
  const range52 =
    metrics?.week52_low && metrics.week52_high
      ? `${formatPrice(metrics.week52_low, currency)} – ${formatPrice(metrics.week52_high, currency)}`
      : "—";
  return (
    <div className="grid gap-x-6 sm:grid-cols-2">
      <dl className="max-sm:border-b max-sm:border-border">
        <Stat label="Open" value={formatPrice(quote?.open, currency)} />
        <Stat label="Previous close" value={formatPrice(quote?.prev_close, currency)} />
        <Stat
          label="Day range"
          value={quote?.low && quote.high ? `${formatPrice(quote.low, currency)} – ${formatPrice(quote.high, currency)}` : "—"}
        />
        <Stat label="52-week range" value={range52} />
        <Stat label="Avg volume (10d)" value={formatCompact(metrics?.avg_volume_10d)} />
      </dl>
      <dl>
        <Stat label="P/E (TTM)" value={formatNumber(metrics?.pe_ttm)} />
        <Stat label="EPS (TTM)" value={formatPrice(metrics?.eps_ttm, currency)} />
        <Stat label="Beta" value={formatNumber(metrics?.beta)} />
        <Stat label="Dividend yield" value={formatPct(metrics?.dividend_yield_pct, false)} />
        <Stat label="Net margin (TTM)" value={formatPct(metrics?.net_margin_ttm_pct, false)} />
      </dl>
    </div>
  );
}

export function CompanyProfileCard({ profile }: { profile: CompanyProfile }) {
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        {profile.logo_url && (
          // Remote logos come from the provider's CDN; next/image would need its domain allow-listed.
          // eslint-disable-next-line @next/next/no-img-element
          <img src={profile.logo_url} alt="" width={32} height={32} className="rounded-sm bg-white" />
        )}
        <div>
          <p className="text-sm font-medium text-primary">{profile.name}</p>
          <p className="text-xs text-secondary">
            {[profile.industry, profile.country].filter(Boolean).join(" · ") || "—"}
          </p>
        </div>
      </div>
      <dl>
        <Stat label="Market cap" value={formatCompact(profile.market_cap, profile.currency)} />
        <Stat label="Shares outstanding" value={formatCompact(profile.shares_outstanding)} />
        <Stat label="Exchange" value={profile.exchange ?? "—"} />
        <Stat label="IPO date" value={profile.ipo_date ? formatDate(profile.ipo_date) : "—"} />
      </dl>
      {profile.website && (
        <a
          href={profile.website}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-block text-[13px] text-accent hover:underline"
        >
          Company website ↗
        </a>
      )}
    </div>
  );
}

export function NewsList({ items }: { items: NewsItem[] }) {
  if (items.length === 0) {
    return <EmptyState title="No news in the last 7 days" />;
  }
  return (
    <ul className="divide-y divide-border">
      {items.map((item) => (
        <li key={item.id} className="py-2 first:pt-0 last:pb-0">
          <a href={item.url} target="_blank" rel="noopener noreferrer" className="group block">
            <p className="text-[13px] font-medium text-primary group-hover:text-accent">{item.headline}</p>
            {item.summary && <p className="mt-0.5 line-clamp-1 text-xs text-secondary">{item.summary}</p>}
            <p className="tabular mt-0.5 text-2xs text-muted">
              {item.source} · <time dateTime={item.published_at}>{item.published_at.slice(0, 10)}</time>
            </p>
          </a>
        </li>
      ))}
    </ul>
  );
}

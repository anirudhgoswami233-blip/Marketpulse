import type { Metadata } from "next";
import { Suspense } from "react";

import { PriceChart } from "@/components/stock/PriceChart";
import { CompanyProfileCard, KeyStats, NewsList } from "@/components/stock/StockDetails";
import { LiveQuote } from "@/components/stock/StockHeader";
import { Card, EmptyState, Skeleton, SkeletonBlock } from "@/components/ui/primitives";
import { ErrorState, StaleBadge } from "@/components/ui/status";
import { ApiError, api, toApiError } from "@/lib/api";
import type { Envelope, SymbolInfo } from "@/types/api";

export async function generateMetadata({ params }: PageProps<"/stock/[symbol]">): Promise<Metadata> {
  const { symbol } = await params;
  return { title: decodeURIComponent(symbol).toUpperCase() };
}

export default function StockPage({ params }: PageProps<"/stock/[symbol]">) {
  return (
    <Suspense fallback={<StockSkeleton />}>
      <StockContent params={params} />
    </Suspense>
  );
}

/** Settle a request into data or a typed error, so one failing section never breaks the page. */
async function settle<T>(promise: Promise<T>): Promise<{ data: T; error: null } | { data: null; error: ApiError }> {
  try {
    return { data: await promise, error: null };
  } catch (error) {
    return { data: null, error: toApiError(error) };
  }
}

async function StockContent({ params }: { params: PageProps<"/stock/[symbol]">["params"] }) {
  const symbol = decodeURIComponent((await params).symbol).toUpperCase();
  const info = await settle(api.stock(symbol));
  if (info.error) {
    if (info.error.code === "not_found") {
      return (
        <EmptyState title={`We couldn't find “${symbol}”`}>
          Try searching by company name. Our directory covers US-listed stocks, ETFs and forex pairs.
        </EmptyState>
      );
    }
    return <ErrorState message={info.error.message} retryable={info.error.retryable} />;
  }
  const stock = info.data;

  return (
    <div className="space-y-6">
      <div>
        <p className="text-xs text-muted">
          {stock.exchange} · {stock.type || "Security"}
          {stock.currency && ` · ${stock.currency}`}
        </p>
        <h1 className="text-2xl font-semibold text-primary">
          {stock.display_symbol} <span className="text-base font-normal text-secondary">{stock.description}</span>
        </h1>
        <div className="mt-3">
          <Suspense fallback={<Skeleton className="h-12 w-64" />}>
            <QuoteSection stock={stock} />
          </Suspense>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
        <Card title="Price chart">
          {stock.price_available ? (
            <PriceChart symbol={stock.symbol} currency={stock.currency} />
          ) : (
            <EmptyState title="Charts aren't available for this exchange">
              Our current data plan covers prices for US-listed securities only.
            </EmptyState>
          )}
        </Card>
        <Card title="Company profile">
          <Suspense fallback={<SkeletonBlock lines={6} label="Loading profile" />}>
            <ProfileSection symbol={stock.symbol} />
          </Suspense>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-[1fr_1fr]">
        <Card title="Key statistics">
          <Suspense fallback={<SkeletonBlock lines={6} label="Loading statistics" />}>
            <StatsSection stock={stock} />
          </Suspense>
        </Card>
        <Card title="Latest news">
          <Suspense fallback={<SkeletonBlock lines={8} label="Loading news" />}>
            <NewsSection symbol={stock.symbol} />
          </Suspense>
        </Card>
      </div>
    </div>
  );
}

async function QuoteSection({ stock }: { stock: SymbolInfo }) {
  if (!stock.price_available) {
    return <p className="text-sm text-secondary">Live prices for {stock.exchange} listings aren&apos;t on our current data plan.</p>;
  }
  const quote = await settle(api.quote(stock.symbol));
  if (quote.error) return <ErrorState message={quote.error.message} retryable={quote.error.retryable} />;
  return <LiveQuote info={stock} quote={quote.data} />;
}

async function ProfileSection({ symbol }: { symbol: string }) {
  const profile = await settle(api.profile(symbol));
  if (profile.error) {
    if (profile.error.code === "no_data" || profile.error.code === "unavailable") {
      return <EmptyState title="No company profile available" />;
    }
    return <ErrorState message={profile.error.message} retryable={profile.error.retryable} />;
  }
  return (
    <>
      <CompanyProfileCard profile={profile.data.data} />
      <Freshness envelope={profile.data} />
    </>
  );
}

async function StatsSection({ stock }: { stock: SymbolInfo }) {
  const [quote, metrics] = await Promise.all([
    stock.price_available ? settle(api.quote(stock.symbol)) : Promise.resolve(null),
    settle(api.metrics(stock.symbol)),
  ]);
  const quoteData = quote?.data?.data ?? null;
  const metricsData = metrics.data?.data ?? null;
  if (!quoteData && !metricsData && metrics.error && metrics.error.retryable) {
    return <ErrorState message={metrics.error.message} />;
  }
  return (
    <>
      <KeyStats quote={quoteData} metrics={metricsData} currency={stock.currency} />
      {metrics.data && <Freshness envelope={metrics.data} />}
    </>
  );
}

async function NewsSection({ symbol }: { symbol: string }) {
  const news = await settle(api.news(symbol));
  if (news.error) return <ErrorState message={news.error.message} retryable={news.error.retryable} />;
  return (
    <>
      <NewsList items={news.data.data} />
      <Freshness envelope={news.data} />
    </>
  );
}

function Freshness<T>({ envelope }: { envelope: Envelope<T> }) {
  if (!envelope.stale) return null;
  return (
    <div className="mt-3">
      <StaleBadge asOf={envelope.as_of} stale />
    </div>
  );
}

function StockSkeleton() {
  return (
    <div className="space-y-6" role="status" aria-label="Loading stock">
      <div className="space-y-2">
        <Skeleton className="h-3 w-32" />
        <Skeleton className="h-7 w-72" />
        <Skeleton className="h-10 w-56" />
      </div>
      <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
        <Card>
          <Skeleton className="h-80 w-full" />
        </Card>
        <Card>
          <SkeletonBlock lines={6} />
        </Card>
      </div>
    </div>
  );
}

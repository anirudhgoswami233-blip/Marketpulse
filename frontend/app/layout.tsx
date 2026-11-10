import { Analytics } from "@vercel/analytics/next";
import type { Metadata } from "next";
import { Geist } from "next/font/google";
import Link from "next/link";
import { Suspense } from "react";

import { AuthNav } from "@/components/auth/AuthNav";
import { MainNav } from "@/components/layout/MainNav";
import { ThemeToggle } from "@/components/layout/ThemeToggle";
import { SearchBox } from "@/components/search/SearchBox";
import { Skeleton } from "@/components/ui/primitives";
import { AuthProvider } from "@/lib/auth";
import { themeInitScript } from "@/lib/theme";

import "./globals.css";

// next/font downloads the font at build time and serves it from this site (no request to Google), with a
// size-adjusted fallback so the swap doesn't shift the layout.
const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"], display: "swap" });

export const metadata: Metadata = {
  title: { default: "MarketPulse", template: "%s · MarketPulse" },
  description: "Global markets, live quotes and a daily market brief.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${geistSans.variable} h-full antialiased`}
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
      </head>
      <body className="flex min-h-full flex-col">
        <AuthProvider>
          <header className="sticky top-0 z-30 border-b border-border bg-surface">
            <div className="relative mx-auto flex max-w-7xl flex-wrap items-center gap-x-3 gap-y-2 px-4 py-2">
              <Link href="/" className="text-[15px] font-semibold tracking-tight text-primary">
                MarketPulse
              </Link>
              {/* MainNav highlights the current route (usePathname), which is request-time data on dynamic routes. */}
              <Suspense fallback={<Skeleton className="h-7 w-20 lg:w-[30rem]" />}>
                <MainNav />
              </Suspense>
              <div className="order-last w-full sm:order-none sm:ml-auto sm:flex sm:w-auto sm:flex-1 sm:justify-end">
                <SearchBox />
              </div>
              <div className="ml-auto flex items-center gap-2 sm:ml-0">
                <ThemeToggle />
                {/* AuthNav reads the current path (for ?next=), which is request-time data on dynamic routes. */}
                <Suspense fallback={<Skeleton className="h-7 w-16" />}>
                  <AuthNav />
                </Suspense>
              </div>
            </div>
          </header>
          <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-4">{children}</main>
          <footer className="border-t border-border px-4 py-3 text-center text-xs text-muted">
            Market data from Finnhub and Twelve Data; may be delayed. Paper trading uses virtual money. Educational
            information, not financial advice.
          </footer>
        </AuthProvider>
        {/* Vercel Web Analytics: page views only, no cookies. Inert outside Vercel deployments. */}
        <Analytics />
      </body>
    </html>
  );
}

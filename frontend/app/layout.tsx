import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
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

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: { default: "MarketPulse", template: "%s · MarketPulse" },
  description: "Global markets, live quotes and a daily market brief.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
      </head>
      <body className="flex min-h-full flex-col">
        <AuthProvider>
          <header className="sticky top-0 z-30 border-b border-border bg-bg/90 backdrop-blur">
            <div className="relative mx-auto flex max-w-7xl flex-wrap items-center gap-3 px-4 py-3">
              <Link href="/" className="text-lg font-bold tracking-tight text-primary">
                Market<span className="text-accent">Pulse</span>
              </Link>
              {/* MainNav highlights the current route (usePathname), which is request-time data on dynamic routes. */}
              <Suspense fallback={<Skeleton className="h-8 w-24" />}>
                <MainNav />
              </Suspense>
              <div className="order-last w-full sm:order-none sm:ml-auto sm:flex sm:w-auto sm:flex-1 sm:justify-end">
                <SearchBox />
              </div>
              <div className="ml-auto flex items-center gap-2 sm:ml-0">
                <ThemeToggle />
                {/* AuthNav reads the current path (for ?next=), which is request-time data on dynamic routes. */}
                <Suspense fallback={<Skeleton className="h-8 w-20" />}>
                  <AuthNav />
                </Suspense>
              </div>
            </div>
          </header>
          <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6">{children}</main>
          <footer className="border-t border-border px-4 py-4 text-center text-xs text-muted">
            Market data from Finnhub and Twelve Data; may be delayed. Paper trading uses virtual money. Educational
            information, not financial advice.
          </footer>
        </AuthProvider>
      </body>
    </html>
  );
}

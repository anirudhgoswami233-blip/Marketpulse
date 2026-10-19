"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { EmptyState, SkeletonBlock } from "@/components/ui/primitives";
import { useAuth } from "@/lib/auth";

/** Renders children only for signed-in users; otherwise a sign-in prompt (no redirect flash). */
export function RequireAuth({ children, what }: { children: ReactNode; what: string }) {
  const { status } = useAuth();
  const pathname = usePathname();
  if (status === "loading") return <SkeletonBlock lines={6} label="Checking your session" />;
  if (status === "anonymous") {
    return (
      <EmptyState title={`Sign in to see your ${what}`}>
        <Link href={`/login?next=${encodeURIComponent(pathname ?? "/")}`} className="text-accent hover:underline">
          Sign in
        </Link>{" "}
        or{" "}
        <Link href={`/register?next=${encodeURIComponent(pathname ?? "/")}`} className="text-accent hover:underline">
          create a free account
        </Link>
        .
      </EmptyState>
    );
  }
  return <>{children}</>;
}

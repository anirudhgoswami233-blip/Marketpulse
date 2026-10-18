"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

/** Re-render the route's server components periodically (e.g. to pick up a new market snapshot). */
export function AutoRefresh({ intervalMs }: { intervalMs: number }) {
  const router = useRouter();
  useEffect(() => {
    const id = window.setInterval(() => {
      if (document.visibilityState === "visible") router.refresh();
    }, intervalMs);
    return () => window.clearInterval(id);
  }, [router, intervalMs]);
  return null;
}

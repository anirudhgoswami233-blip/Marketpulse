"use client";

import { ErrorState } from "@/components/ui/status";

// Route-level safety net: sections handle their own errors, so reaching this means something unexpected broke.
export default function RouteError({ retry }: { error: unknown; retry: () => void }) {
  return (
    <div className="mx-auto max-w-xl py-10">
      <ErrorState message="This page hit an unexpected problem." onRetry={retry} />
    </div>
  );
}

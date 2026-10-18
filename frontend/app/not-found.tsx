import Link from "next/link";

import { EmptyState } from "@/components/ui/primitives";

export default function NotFound() {
  return (
    <div className="mx-auto max-w-xl py-10">
      <EmptyState title="Page not found">
        <Link href="/" className="text-accent hover:underline">
          Back to markets
        </Link>
      </EmptyState>
    </div>
  );
}

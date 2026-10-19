"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { Skeleton } from "@/components/ui/primitives";
import { useAuth } from "@/lib/auth";

export function AuthNav() {
  const { status, user, logout } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  if (status === "loading") return <Skeleton className="h-8 w-20" />;
  if (status === "anonymous") {
    const next = pathname && pathname !== "/login" && pathname !== "/register" ? `?next=${encodeURIComponent(pathname)}` : "";
    return (
      <Link
        href={`/login${next}`}
        className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium whitespace-nowrap text-surface hover:opacity-90"
      >
        Sign in
      </Link>
    );
  }
  return (
    <div className="flex items-center gap-2 text-sm">
      <span className="hidden max-w-32 truncate text-secondary sm:inline" title={user?.email}>
        {user?.display_name}
      </span>
      <button
        type="button"
        onClick={async () => {
          await logout();
          router.push("/");
        }}
        className="rounded-md border border-border px-2.5 py-1.5 text-secondary whitespace-nowrap hover:text-primary"
      >
        Sign out
      </button>
    </div>
  );
}

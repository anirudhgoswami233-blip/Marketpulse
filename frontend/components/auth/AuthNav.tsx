"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { Skeleton } from "@/components/ui/primitives";
import { useAuth } from "@/lib/auth";

export function AuthNav() {
  const { status, user, logout } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  if (status === "loading") return <Skeleton className="h-7 w-16" />;
  if (status === "anonymous") {
    const next = pathname && pathname !== "/login" && pathname !== "/register" ? `?next=${encodeURIComponent(pathname)}` : "";
    return (
      <Link
        href={`/login${next}`}
        className="btn btn-md btn-primary"
      >
        Sign in
      </Link>
    );
  }
  return (
    <div className="flex items-center gap-2 text-[13px]">
      <span className="hidden max-w-32 truncate text-secondary sm:inline" title={user?.email}>
        {user?.display_name}
      </span>
      <button
        type="button"
        onClick={async () => {
          await logout();
          router.push("/");
        }}
        className="btn btn-md"
      >
        Sign out
      </button>
    </div>
  );
}

"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useId, useState } from "react";

export const NAV_GROUPS: { label: string; links: { href: string; label: string }[] }[] = [
  {
    label: "Markets",
    links: [
      { href: "/", label: "Markets" },
      { href: "/forex", label: "Forex" },
      { href: "/macro", label: "Macro" },
      { href: "/calendar", label: "Calendar" },
    ],
  },
  {
    label: "Your tools",
    links: [
      { href: "/watchlists", label: "Watchlists" },
      { href: "/portfolio", label: "Portfolio" },
      { href: "/brief", label: "Brief" },
      { href: "/signals", label: "Signals" },
    ],
  },
];

export function isActive(pathname: string | null, href: string): boolean {
  if (!pathname) return false;
  return href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
}

function NavLink({ href, label, pathname }: { href: string; label: string; pathname: string | null }) {
  const active = isActive(pathname, href);
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      className={`rounded-md px-2 py-1 ${active ? "bg-surface-2 font-medium text-primary" : "text-secondary hover:text-primary"}`}
    >
      {label}
    </Link>
  );
}

/** Grouped links on wide screens; a disclosure menu on phones. Closes on navigation and Escape. */
export function MainNav() {
  const pathname = usePathname();
  const menuId = useId();
  const [openFor, setOpenFor] = useState<string | null>(null);
  // The menu belongs to the page it was opened on, so navigating closes it without an effect.
  const open = openFor !== null && openFor === pathname;

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && setOpenFor(null);
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <>
      <nav aria-label="Main" className="hidden items-center gap-1 text-sm lg:flex">
        {NAV_GROUPS.map((group, i) => (
          <div key={group.label} className="flex items-center gap-1">
            {i > 0 && <span aria-hidden className="mx-1 h-4 w-px bg-border" />}
            {group.links.map((link) => (
              <NavLink key={link.href} {...link} pathname={pathname} />
            ))}
          </div>
        ))}
      </nav>
      <div className="lg:hidden">
        <button
          type="button"
          aria-expanded={open}
          aria-controls={menuId}
          onClick={() => setOpenFor(open ? null : (pathname ?? "/"))}
          className="rounded-md border border-border px-2.5 py-1.5 text-sm text-secondary hover:text-primary"
        >
          <span aria-hidden>{open ? "✕" : "☰"}</span> Menu
        </button>
        {open && (
          <nav
            id={menuId}
            aria-label="Main"
            className="absolute inset-x-0 top-full z-40 border-b border-border bg-bg px-4 py-3 shadow-lg"
          >
            <div className="mx-auto grid max-w-7xl grid-cols-2 gap-4 text-sm">
              {NAV_GROUPS.map((group) => (
                <div key={group.label}>
                  <p className="mb-1 text-xs font-semibold tracking-wide text-muted uppercase">{group.label}</p>
                  <div className="flex flex-col gap-0.5">
                    {group.links.map((link) => (
                      <NavLink key={link.href} {...link} pathname={pathname} />
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </nav>
        )}
      </div>
    </>
  );
}

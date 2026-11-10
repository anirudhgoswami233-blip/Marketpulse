"use client";

import { useEffect, useRef, type ReactNode } from "react";

/**
 * Wraps a displayed price and flashes its background briefly when `value` changes: green for an uptick,
 * red for a downtick. The flash is a CSS animation, so `prefers-reduced-motion` turns it off (globals.css);
 * the number itself, and the ▲/▼ beside it, still carry the change.
 */
export function PriceTick({ value, children, className = "" }: { value: string | number | null; children: ReactNode; className?: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const previous = useRef<number | null>(null);

  useEffect(() => {
    const next = value === null ? NaN : Number(value);
    const before = previous.current;
    previous.current = Number.isFinite(next) ? next : null;
    const el = ref.current;
    if (!el || before === null || !Number.isFinite(next) || next === before) return;
    el.classList.remove("tick-up", "tick-down");
    // Reading layout restarts the animation when two ticks in the same direction arrive back to back.
    void el.offsetWidth;
    el.classList.add(next > before ? "tick-up" : "tick-down");
  }, [value]);

  return (
    <span ref={ref} className={`tick tabular ${className}`}>
      {children}
    </span>
  );
}

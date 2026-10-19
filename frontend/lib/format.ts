// Locale-aware formatting. Prices arrive as decimal strings; convert to number only for display.

const LOCALE = undefined; // the viewer's locale

function toNumber(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n : null;
}

export function formatPrice(value: string | number | null | undefined, currency?: string | null): string {
  const n = toNumber(value);
  if (n === null) return "—";
  const digits = Math.abs(n) >= 1 ? 2 : 4;
  if (currency) {
    try {
      return new Intl.NumberFormat(LOCALE, {
        style: "currency",
        currency,
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      }).format(n);
    } catch {
      // Unknown currency code: fall through to a plain number.
    }
  }
  return new Intl.NumberFormat(LOCALE, { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(n);
}

/** Money amounts (cash, equity, P&L, order totals): always 2 decimals, unlike share prices. */
export function formatMoney(value: string | number | null | undefined, currency?: string | null): string {
  const n = toNumber(value);
  if (n === null) return "—";
  const options: Intl.NumberFormatOptions = { minimumFractionDigits: 2, maximumFractionDigits: 2 };
  if (currency) {
    try {
      return new Intl.NumberFormat(LOCALE, { ...options, style: "currency", currency }).format(n);
    } catch {
      // Unknown currency code: fall through to a plain number.
    }
  }
  return new Intl.NumberFormat(LOCALE, options).format(n);
}

/** Signed change, e.g. "+1.46" or "−0.32". */
export function formatChange(value: string | number | null | undefined): string {
  const n = toNumber(value);
  if (n === null) return "—";
  return new Intl.NumberFormat(LOCALE, {
    signDisplay: "exceptZero",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(n);
}

/** Signed percentage from a percent value (1.5 means 1.5%). */
export function formatPct(value: string | number | null | undefined, signed = true): string {
  const n = toNumber(value);
  if (n === null) return "—";
  return new Intl.NumberFormat(LOCALE, {
    style: "percent",
    signDisplay: signed ? "exceptZero" : "auto",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(n / 100);
}

/** Compact magnitude for market cap and volume, e.g. "3.75T" or "$3.75T". */
export function formatCompact(value: string | number | null | undefined, currency?: string | null): string {
  const n = toNumber(value);
  if (n === null) return "—";
  const options: Intl.NumberFormatOptions = { notation: "compact", maximumFractionDigits: 2 };
  if (currency) {
    try {
      return new Intl.NumberFormat(LOCALE, { ...options, style: "currency", currency }).format(n);
    } catch {
      // fall through
    }
  }
  return new Intl.NumberFormat(LOCALE, options).format(n);
}

export function formatNumber(value: string | number | null | undefined, digits = 2): string {
  const n = toNumber(value);
  if (n === null) return "—";
  return new Intl.NumberFormat(LOCALE, { maximumFractionDigits: digits }).format(n);
}

export type Direction = "up" | "down" | "flat";

export function direction(value: string | number | null | undefined): Direction {
  const n = toNumber(value);
  if (n === null || n === 0) return "flat";
  return n > 0 ? "up" : "down";
}

/** Time of day in a specific timezone (deterministic on server and client), e.g. "09:30". */
export function formatTimeIn(iso: string, timeZone: string): string {
  return new Intl.DateTimeFormat(LOCALE, { hour: "2-digit", minute: "2-digit", timeZone }).format(new Date(iso));
}

/** Time of day in the viewer's timezone. Only call from client components after hydration. */
export function formatLocalTime(iso: string): string {
  return new Intl.DateTimeFormat(LOCALE, { hour: "2-digit", minute: "2-digit" }).format(new Date(iso));
}

export function formatLocalDateTime(iso: string): string {
  return new Intl.DateTimeFormat(LOCALE, { dateStyle: "medium", timeStyle: "short" }).format(new Date(iso));
}

export function formatDate(isoDate: string): string {
  // Date-only strings (YYYY-MM-DD) are calendar dates: format in UTC so they don't shift a day.
  return new Intl.DateTimeFormat(LOCALE, { dateStyle: "medium", timeZone: "UTC" }).format(new Date(isoDate));
}

/** "in 2h 15m" / "in 45m" until a future instant, relative to `now`. */
export function formatCountdown(iso: string, now: number): string {
  const minutes = Math.max(0, Math.round((new Date(iso).getTime() - now) / 60_000));
  if (minutes < 60) return `in ${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `in ${hours}h ${minutes % 60}m`;
  return `in ${Math.round(hours / 24)}d`;
}

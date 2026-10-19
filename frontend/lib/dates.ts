// Calendar-date helpers that respect the viewer's timezone. Only call these from client code after hydration
// (they read the clock), never while a server component prerenders.

/** The browser's IANA timezone, or "UTC" if it can't be determined. */
export function browserTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

/** The timezone to use for "today": the signed-in user's profile setting, else the browser's. */
export function viewerTimeZone(profileTimeZone: string | null | undefined): string {
  if (profileTimeZone) {
    try {
      new Intl.DateTimeFormat("en-US", { timeZone: profileTimeZone });
      return profileTimeZone;
    } catch {
      // An unknown zone in the profile shouldn't break the page: fall back to the browser's.
    }
  }
  return browserTimeZone();
}

/** Today's calendar date (YYYY-MM-DD) in `timeZone`. */
export function todayIn(timeZone: string, now: Date = new Date()): string {
  // en-CA formats dates as YYYY-MM-DD.
  return new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit" }).format(now);
}

// Theme resolution: an explicit choice (data-theme on <html>, persisted in localStorage) wins; with no
// choice we follow the operating system's prefers-color-scheme, including live changes.

export type Theme = "dark" | "light";

export const THEME_STORAGE_KEY = "mp-theme";
const DARK_QUERY = "(prefers-color-scheme: dark)";

/**
 * Inline script for <head>: applies a saved choice before first paint. Without one it does nothing, and
 * the CSS media query picks the system theme, so there's no flash either way.
 */
export const themeInitScript = `(function(){try{var t=localStorage.getItem("${THEME_STORAGE_KEY}");if(t==="light"||t==="dark")document.documentElement.setAttribute("data-theme",t)}catch(e){}})()`;

export function resolveTheme(explicit: string | null, systemPrefersDark: boolean): Theme {
  if (explicit === "light" || explicit === "dark") return explicit;
  return systemPrefersDark ? "dark" : "light";
}

export function readTheme(): Theme {
  const systemDark = typeof window.matchMedia === "function" && window.matchMedia(DARK_QUERY).matches;
  return resolveTheme(document.documentElement.getAttribute("data-theme"), systemDark);
}

/** Calls `onChange` when the user toggles the theme or the OS theme changes. Returns an unsubscribe. */
export function subscribeTheme(onChange: () => void): () => void {
  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  const media = typeof window.matchMedia === "function" ? window.matchMedia(DARK_QUERY) : null;
  media?.addEventListener("change", onChange);
  return () => {
    observer.disconnect();
    media?.removeEventListener("change", onChange);
  };
}

/** Persist and apply an explicit choice; from then on the OS theme no longer applies. */
export function setTheme(theme: Theme): void {
  document.documentElement.setAttribute("data-theme", theme);
  try {
    localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // Storage unavailable (private mode): the choice lasts for this page view.
  }
}

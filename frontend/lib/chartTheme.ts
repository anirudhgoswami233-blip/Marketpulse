// Chart styling from the design tokens in app/globals.css, shared by every lightweight-charts instance.

/**
 * Resolve a color token (e.g. "--chart-line") to a concrete color for the canvas. Tokens are light-dark()
 * expressions, which only CSS can evaluate, so read the computed color off a probe element.
 */
export function tokenColor(name: string): string {
  const probe = document.createElement("span");
  probe.style.display = "none";
  probe.style.color = `var(${name})`;
  document.body.appendChild(probe);
  const color = getComputedStyle(probe).color;
  probe.remove();
  return color;
}

/** Layout, grid and axis options: muted horizontal gridlines only, no borders, UI font. */
export function chartThemeOptions() {
  return {
    layout: {
      background: { color: "transparent" },
      textColor: tokenColor("--text-muted"),
      fontFamily: getComputedStyle(document.body).fontFamily,
      fontSize: 11,
    },
    grid: { vertLines: { visible: false }, horzLines: { color: tokenColor("--chart-grid") } },
    crosshair: {
      vertLine: { color: tokenColor("--border-strong"), labelBackgroundColor: tokenColor("--text-secondary") },
      horzLine: { color: tokenColor("--border-strong"), labelBackgroundColor: tokenColor("--text-secondary") },
    },
    rightPriceScale: { borderVisible: false },
    timeScale: { borderVisible: false },
  };
}

/** A thin solid line in the accent color: no area fill, no gradient. */
export function lineSeriesOptions() {
  return { color: tokenColor("--chart-line"), lineWidth: 1 as const, priceLineVisible: false };
}

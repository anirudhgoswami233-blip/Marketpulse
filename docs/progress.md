# MarketPulse progress

Phase status and requests carried forward between phases. Update this file when a phase ends or a
request is deferred.

## Phases

| Phase | Scope | Status |
|---|---|---|
| 1 | Backend skeleton, provider layer, rate limiter, caching | Done |
| 2 | Markets overview, search, stock pages, live prices, Next.js shell | Done |
| 3 | Auth, watchlists, paper trading | Done |
| 4 | Signal engine, Daily Brief, Signal History | In progress |
| 5 | Forex & metals, macro dashboard, earnings/IPO calendar | Not started |
| 6 | Polish, performance, README, test gaps | Not started |

## Deferred requests

### Phase 5
- **Forex and metals prices and charts.** Searching gold (`OANDA:XAU_USD`) currently shows no price or chart.
  Route forex and metals (XAU/USD, EUR/USD, USD/INR, …) through Twelve Data for quotes and charts.
  Finnhub's free tier blocks forex quotes and candles (see `finnhub-endpoints.md`); the Twelve Data
  adapter already maps `OANDA:EUR_USD` → `EUR/USD`.
- **Explain missing prices on actions.** On pages without price data, the watchlist and trade options
  should say that prices won't show for this symbol, rather than the controls simply missing or the
  watchlist row saying "Not on our data plan" with no further context.

### Phase 6
- **Dev-mode page loads feel slow.** Investigate and improve as part of polish. Measure the production build
  (`npm run build && npm start`) separately from `next dev`, since dev mode compiles routes on demand.

# MarketPulse progress

Phase status and requests carried forward between phases. Update this file when a phase ends or a
request is deferred.

## Phases

| Phase | Scope | Status |
|---|---|---|
| 1 | Backend skeleton, provider layer, rate limiter, caching | Done |
| 2 | Markets overview, search, stock pages, live prices, Next.js shell | Done |
| 3 | Auth, watchlists, paper trading | Done |
| 4 | Signal engine, Daily Brief, Signal History | Done |
| 5 | Forex & metals, macro dashboard, earnings/IPO calendar | Done |
| 6 | Polish, performance, README, test gaps | Not started |

## Deferred requests

### Phase 5 (done 2026-10-19)
- ~~Forex and metals prices and charts~~ via Twelve Data: quotes (5-min cache, labelled delayed), charts,
  signals. INR pairs added under the `FX` pseudo-exchange (`seed_symbols.py --extras-only`).
- ~~Explain missing prices on actions~~: the backend's `price_note` / `trade_note` show next to the
  watchlist control, instead of the trade panel, and in watchlist rows.
- **Found while building:** Twelve Data's free plan doesn't price silver (XAG/USD returns "not available on
  our plan"); platinum and palladium are assumed the same and are shown as unpriced with that explanation.

### Decisions
- **Daily Brief text stays templated** (decided 2026-10-19). The optional LLM rewrite from the original spec
  is skipped for now: no provider and no new dependency. The `BriefWriter` hook in
  `services/brief_service.py` stays, so an LLM writer can be added later without touching the job.

### Phase 6
- **Twelve Data budget is shared across servers.** Each backend process has its own 750/day limiter, but the
  vendor counts 800/day per key. Two servers on one key (e.g. a dev server plus a test server) can overspend.
  With Redis configured the limiter is shared; consider requiring Redis outside dev.
- **Long header nav.** Nine links now wrap on medium screens; consider grouping (Markets / Forex / Macro /
  Calendar vs. My stuff).
- **Brief overnight section needs the market snapshot.** A brief generated before the overview snapshot job
  has run (e.g. right after a server start) shows "n/a" for regions and no trending symbols. Consider
  warming the snapshot first or letting the brief job fetch the regional ETF quotes itself.
- **Dev-mode page loads feel slow.** Investigate and improve as part of polish. Measure the production build
  (`npm run build && npm start`) separately from `next dev`, since dev mode compiles routes on demand.

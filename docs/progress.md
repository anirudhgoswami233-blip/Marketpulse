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
| 6 | Polish, performance, README, test gaps | Done |

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

### Phase 6 (done 2026-10-19)
- ~~Twelve Data budget shared across servers~~: the backend now refuses to start outside dev without
  `REDIS_URL` (`check_shared_state` in `container.py`), and warns in dev.
- ~~Long header nav~~: grouped into Markets (Markets / Forex / Macro / Calendar) and Your tools (Watchlists /
  Portfolio / Brief / Signals), with the current page highlighted. Below `lg` it collapses into a Menu button.
- ~~Brief overnight section needs the snapshot~~: the brief job fetches any regional ETF proxies and movers
  missing from the snapshot first (background priority, partial refresh).
- ~~Dev-mode slowness~~: the cause was Windows resolving `localhost` to IPv6 first, which added ~200 ms to
  every new connection. Server-side fetches now default to 127.0.0.1, bringing backend calls from ~220 ms
  to under 10 ms. The remaining first-visit delay is `next dev` compiling the route (1–2 s once).
- Calendar's default week uses the viewer's timezone (profile, or the browser when signed out). The week is
  worked out on the client, so the server never reads the clock.
- Phone-width check (375 px): no page scrolls sideways. Wide tables scroll inside their cards.
- README, `docker-compose.yml` (optional Postgres + Redis), loading/error states on the brief teaser.

### Possible next steps (not requested)
- LLM-written brief through the existing `BriefWriter` hook.
- A paid data plan would unlock non-US quotes, real index levels and silver/platinum/palladium.

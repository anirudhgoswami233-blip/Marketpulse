# MarketPulse

**[Live demo →](https://marketpulse-rose-seven.vercel.app)**

> The backend runs on Render's free tier and sleeps after ~15 idle minutes. If nobody has used the demo for a
> while, the first load can take ~50 s while it wakes up; after that pages load normally.

A global stock-market web app: a live markets overview, per-symbol stock pages, forex and metals, a macro
dashboard, earnings and IPO calendars, search, watchlists, paper trading, and a personalised **Daily Market
Brief** built from technical signals. It runs end to end on free API tiers by funnelling every external call
through a shared rate limiter and cache, and by caching public pages so visitors rarely wait on the backend.

> Signals are educational information based on technical indicators, not financial advice. Paper trading uses
> virtual money.

## Stack

- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2 (async) + Alembic, APScheduler, httpx. SQLite in dev,
  PostgreSQL in production. Redis for the shared cache and rate limiter (in-memory fallback in dev).
- **Frontend:** Next.js 16 (App Router, Cache Components), TypeScript strict, Tailwind CSS v4, TradingView
  Lightweight Charts. Self-hosted font via `next/font`; no UI component library.
- **Data:** Finnhub (primary, free tier), Twelve Data (price history, forex and metals), FRED (macro).
- **Auth:** argon2 password hashing, short-lived JWT access tokens, rotating opaque httpOnly refresh cookie.

---

## How it fits together

```
Browser ── Next.js (Vercel) ───────────────► FastAPI (Render) ──► Postgres (Neon)
  │          · server components (cached)          │   · services → provider registry
  │          · /api/v1/* proxied first-party       │   · rate limiter + cache (Redis / Upstash)
  │                                                 │   · APScheduler jobs
  └── SSE /stream ◄───── fan-out hub ◄── one shared WebSocket ──► Finnhub / Twelve Data / FRED
```

- **One rule for external data.** Services never name a vendor. They ask a **provider registry** for a
  capability ("quote for this exchange", "daily history", "macro series"), and every call goes through
  **provider adapter → rate limiter → cache**. Swapping or adding a provider touches only the registry.
- **Two cache layers.** The backend caches provider responses (Redis in prod, in-memory in dev). The frontend
  additionally caches whole public pages on Vercel (ISR), so a warm visit renders from cache without calling
  the backend at all.
- **Live vs. cached is a hard line.** Live trade prices stream over a single backend WebSocket and are fanned
  out to browsers via Server-Sent Events; everything else is request/response and cacheable. Per-user data
  (watchlists, portfolio, auth) is never cached.
- **Resilient by default.** On a provider error or rate-limit, the last good value is served with its `as_of`
  timestamp and a `stale` flag; the UI shows "data as of HH:MM" and pages never crash.

---

## The website, page by page

Every page shows a loading skeleton, an empty state, an error state with retry, and a "data as of" label when
it is serving cached data. Routes live in `frontend/app/`; the components in parentheses live in
`frontend/components/`.

| Route | What it is | Key components | Backend |
|---|---|---|---|
| `/` | **Markets overview** — regional index ETF-proxies with live prices, each exchange's open/closed status and countdown, a sector heatmap, and top gainers/losers. | `markets/IndexGrid`, `MarketStatusList`, `SectorHeatmap`, `MoversTable`, `LiveQuotesProvider`, `signals/BriefTeaser` | `GET /markets/overview` + SSE `/stream` |
| `/stock/[symbol]` | **Stock page** — live quote with ▲/▼ change, price chart (1D–5Y), company profile, key statistics, latest news, and a technical signal with its reasons. | `stock/StockHeader` (`LiveQuote`), `PriceChart` → `ChartCanvas` (lazy), `StockDetails`, `StockActions` (add-to-watchlist + paper-trade panel), `signals/SignalCard` | `/stocks/{symbol}` · `/quote` · `/profile` · `/metrics` · `/news` · `/signal` · `/chart` + SSE |
| `/forex` | **Forex & metals** — majors, INR pairs and gold grouped into tables, plus a currency converter. Crosses are marked as derived. | `forex/ForexView` (`RateTable`, `Converter`) | `GET /forex` |
| `/macro` | **Macro dashboard** — FRED series (rates, inflation, jobs) as stat tiles with 5-year mini line charts and a data table. | `macro/MiniLineChart` → `MiniLineCanvas` (lazy) | `GET /macro` |
| `/calendar` | **Earnings & IPO calendar** — one week at a time, filterable, with a "my watchlists only" toggle. Defaults to the current week in your timezone. | `calendar/CalendarView` (`Earnings`, `Ipos`) | `GET /calendar/earnings` · `/calendar/ipos` |
| `/search` | **Search** — full results for a query against the seeded symbol directory (never the provider API). | `search/SearchBox` | `GET /search` |
| `/watchlists` | **Watchlists** (sign-in) — multiple named lists with live prices; add via search, rename, delete. | `portfolio/WatchlistsView`, `SearchBox` | `/watchlists` CRUD + `/watchlists/{id}/items` |
| `/portfolio` | **Paper portfolio** (sign-in) — equity/cash/return tiles, open positions revalued live, trade history, reset. | `portfolio/PortfolioView` (`Holdings`, `TradeHistory`) | `/portfolio` · `/portfolio/trades` · `POST /portfolio/orders` · `/reset` |
| `/brief` | **Daily Market Brief** (sign-in) — the latest brief, past briefs, and settings (brief time, timezone, email). | `signals/BriefView` (`BriefContent`, `BriefSettings`) | `GET /brief` · `/briefs` · `/briefs/{date}` · `POST /brief/generate` · `PATCH /me` |
| `/signals` | **Signal history** — stored signals filterable by label, and a table of average return / hit-rate at 1/5/20 days. | `signals/SignalCard` | `GET /signals/history` · `/signals/performance` |
| `/login`, `/register` | **Accounts** — email + password, with `?next=` redirect back. | `auth/AuthForm` | `POST /auth/register` · `/login` · `/refresh` · `/logout` |

**Shared shell** (`app/layout.tsx`): grouped top navigation (`layout/MainNav`), global `SearchBox`, light/dark
`ThemeToggle` (follows the OS on first visit, then remembers your choice), and `auth/AuthNav`. Reusable UI
lives in `components/ui/` — `Card`/`PageHeader`, tables, badges, skeletons, the "data as of" `StaleBadge`,
`ConfirmDialog`, and `PriceTick` (the subtle green/red flash on a live tick, disabled under
`prefers-reduced-motion`).

### Design & performance notes

- A single design-token system in `app/globals.css` (one accent, semantic up/down, light + dark via
  `light-dark()`); flat 1px-bordered surfaces, tabular numerals so live prices don't jitter, WCAG-AA contrast
  in both themes.
- Heavy client code is lazy-loaded with `next/dynamic` (the chart library loads only on pages that draw a
  chart), keeping the shared bundle small.
- Live prices use **one** SSE stream per page via `LiveQuotesProvider`, never one request per widget.

---

## The API

FastAPI, all under `/api/v1`, grouped by router in `backend/app/api/`. Interactive docs at `/docs`.

- **`markets`** — `GET /markets/overview`: the periodic snapshot (index proxies, movers, sectors, exchange
  status).
- **`stocks`** — `GET /stocks/{symbol}` (directory info), `/quote`, `/profile`, `/metrics`, `/news`,
  `/signal`, `/chart?range=`, and `GET /quotes?symbols=` (bulk, for watchlist rows).
- **`world`** — `GET /forex`, `/macro`, `/calendar/earnings`, `/calendar/ipos`, `/search`.
- **`stream`** — `GET /stream?symbols=` (SSE): per-client live-price fan-out from the shared WebSocket.
- **`auth`** — `POST /register`, `/login`, `/refresh`, `/logout`; `GET`/`PATCH /me` (profile, brief settings).
- **`portfolio`** — `GET /portfolio`, `/portfolio/trades`; `POST /portfolio/orders`, `/portfolio/reset`;
  full `/watchlists` CRUD plus `/watchlists/{id}/items`.
- **`signals`** — `GET /brief` (today's status), `/briefs`, `/briefs/{date}`, `POST /brief/generate`;
  `GET /signals/history`, `/signals/performance`.
- **`system`** — `GET /health`, `/system/status`.
- **`internal`** — `GET /internal/jobs`, `POST /internal/jobs/run` (Bearer `CRON_SECRET`): lets an external
  scheduler wake a sleeping host and run the jobs.

Routers stay thin; all logic is in `services/` and `signals/`.

---

## Backend internals

- **`providers/`** — the data layer. `base.py` defines the `MarketDataProvider` interface;
  `finnhub.py` (primary), `fred.py` (macro) and `fallback/twelvedata.py` (price history, forex, metals)
  implement it over a shared `http.py` client; `registry.py` maps each capability to a provider so services
  stay vendor-agnostic.
- **`services/`** — business logic, one module per area: `markets_service`, `quote_service`, `stock_service`,
  `forex_service` (+ `fx_math` for cross rates), `history_service`, `macro_service`, `calendar_service`,
  `search_service`/`symbol_directory`, `market_hours`, `watchlist_service`, `trading_service`
  (+ `portfolio_math`, pure `Decimal` math with optimistic concurrency), `auth_service`, `brief_service`
  (+ `email_service`), `signal_service`, and `reference_data` (the index-proxy and forex configs).
- **`signals/`** — pure, I/O-free indicator math so it is trivially testable: `indicators.py`
  (Wilder-smoothed RSI, MACD, moving averages, 52-week range, volume), `engine.py` (turns readings into a
  labelled score with reasons; `ENGINE_VERSION` namespaces stored history), `sentiment.py` (keyword news
  tone), `performance.py` (scores past signals).
- **`jobs/`** — APScheduler tasks: `market_snapshot` (overview), `forex_snapshot` (board), `daily_brief`
  (per-user, at each user's local time), `signal_outcomes` (1/5/20-session returns). `scheduler.py` wires
  them and `runner.run_exclusive` ensures the in-process scheduler and the external cron never overlap.
- **`ws/`** — `finnhub_stream.py` holds the one allowed Finnhub socket; `hub.py` reference-counts symbol
  subscriptions and fans trades out to SSE clients, subscribing only to symbols someone is viewing/watching.
- **`models/`** — SQLAlchemy models: `user`, `market` (symbols, snapshots, price bars), `portfolio`
  (portfolios, positions, trades, watchlists), `signals` (stored signals, outcomes, briefs).

---

## How the free tiers are respected

| Provider | Vendor limit | App limiter | Notes |
|---|---|---|---|
| Finnhub | ~60/min | **50/min** | One shared backend WebSocket for live trades |
| Twelve Data | 8/min, 800/day | **7/min, 750/day** | One credit per symbol; history cached 24 h, forex/metals 5 min |
| FRED | 120/min | 100/min | Macro series cached |

- **Priorities.** User requests are *interactive*: they wait up to 30 s for a limiter slot, then fall back to
  cached/stale data. Scheduled jobs are *background*: capped at 70% of each per-minute budget and allowed to
  queue, so a brief run never starves a page.
- **Backend caching** (Redis, or in-memory in dev): quotes 60 s, news 15 min, profiles/metrics 24 h, symbol
  lists 7 d, market status 5 min.
- **Live prices.** One WebSocket to Finnhub, reference-counted, fanned out over one SSE stream per page. The
  key never reaches the browser.
- **Search** hits the seeded symbol directory in the database, not the API.
- **Daily Brief jobs** fetch each symbol once for all users and spread calls over time at background priority.

### Free-tier gaps and how the app handles them

- No Finnhub candles → price history comes from Twelve Data.
- No index quotes (`^GSPC`) or non-US quotes on either free tier → global indices appear as US-listed **ETF
  proxies** (SPY, EWJ, INDA, VGK, …), labelled as ETFs. Non-US stocks are searchable, but their pages explain
  there's no price and they can't be paper-traded.
- No Finnhub forex quotes → forex pairs and gold come from Twelve Data; crosses are derived from USD pairs.
  Silver, platinum and palladium aren't on Twelve Data's free plan and are shown with that explanation.
- No news-sentiment endpoint → news tone is a keyword score over recent headlines.

### Page caching (Vercel ISR)

Public, non-user pages are served from Vercel's cache so visitors don't wait on Render. Public data is read
through `frontend/lib/cached.ts` — Cache Components `"use cache"` wrappers with explicit `cacheLife` times
(history & fundamentals: hours · macro: hours · news & forex: 5 min · overview & signals: minutes). Non-param
pages call `await connection()` first, so the cache fills at **request time**, not during `next build` — the
build never depends on the (sleeping) backend. Forex and the price chart are client-fetched but seed from
server-cached data, so they paint instantly and skip the first client fetch. Per-user data and live prices are
never cached, and because `as_of` travels inside the cached payload, "data as of" labels stay accurate.

---

## Quick start

Requires Python 3.12 and Node 20+. Docker is optional.

### 1. Get the API keys (all free)

| Variable | Where to get it | Used for |
|---|---|---|
| `FINNHUB_API_KEY` | Sign up at [finnhub.io](https://finnhub.io/register); key on your [dashboard](https://finnhub.io/dashboard). | US quotes, live trades (WebSocket), profiles, metrics, news, market status, calendars |
| `TWELVEDATA_API_KEY` | Sign up at [twelvedata.com](https://twelvedata.com/pricing) (Basic plan); key under *API Keys*. | Daily price history (charts & signals), forex pairs, gold |
| `FRED_API_KEY` | [Request a key](https://fred.stlouisfed.org/docs/api/api_key.html) with a free FRED account. | Macro dashboard |

The app runs with any of them missing; the affected widgets then say the provider isn't configured.

### 2. Backend

```bash
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements-dev.txt     # macOS/Linux: .venv/bin/pip
cp .env.example .env                                  # then paste your keys into .env
.venv/Scripts/alembic upgrade head
.venv/Scripts/python scripts/seed_symbols.py          # symbol directory for search (run once)
.venv/Scripts/uvicorn app.main:app --reload           # http://127.0.0.1:8000, docs at /docs
```

Optional: `scripts/check_finnhub_endpoints.py` re-checks which Finnhub endpoints your key can use and rewrites
`docs/finnhub-endpoints.md`.

### 3. Frontend

```bash
cd frontend
cp .env.example .env.local
npm install
npm run dev                                           # http://localhost:3000
```

### 4. Optional: PostgreSQL and Redis

```bash
docker compose up -d postgres redis
```

Then set `DATABASE_URL` and `REDIS_URL` in `backend/.env` (see `docker-compose.yml`) and run
`alembic upgrade head` again. **Redis is required outside dev** (`ENV` other than `dev`): without it, each
backend process keeps its own rate-limit counters and would overspend the shared vendor quotas.

## Checks

```bash
# backend
cd backend && .venv/Scripts/ruff format . && .venv/Scripts/ruff check . && .venv/Scripts/mypy app scripts tests
cd backend && .venv/Scripts/pytest -q
# frontend
cd frontend && npm run lint && npm run typecheck && npm test
cd frontend && npm run build    # also enforces Cache Components rules
```

The test suites never call the real APIs: Finnhub, Twelve Data and FRED are mocked (respx on the backend, a
fetch stub on the frontend).

## Deploying

[DEPLOY.md](DEPLOY.md) walks through a free-tier production setup: Vercel (frontend), Render (backend),
Neon (Postgres), Upstash (Redis), and a GitHub Actions schedule that runs the daily jobs while Render sleeps.
Vercel proxies `/api/v1/*` to Render so the refresh cookie stays first-party; SSE connects directly.

## Project layout

```
backend/app/
  api/        thin FastAPI routers (auth, markets, stocks, world, stream, portfolio, signals, system, internal)
  core/       config, security, logging, rate limiter, cache
  providers/  base.py (interface), finnhub.py, fred.py, fallback/twelvedata.py, registry.py
  services/   business logic (markets, quotes, forex, history, macro, calendar, portfolio, brief, …)
  signals/    pure indicator math, scoring engine, news sentiment, performance
  jobs/       APScheduler jobs + scheduler/runner (market snapshot, forex, daily brief, signal outcomes)
  ws/         shared Finnhub WebSocket + reference-counted SSE fan-out
  models/ schemas/   SQLAlchemy models · Pydantic request/response schemas
frontend/
  app/        routes · components/ (by feature + ui/) · lib/ (api client, cached.ts, hooks, formatters) · types/
docs/         finnhub-endpoints.md (free-tier check), progress.md (phase notes and decisions)
```

## Configuration

All backend settings live in `backend/.env`, each documented in `backend/.env.example`; secrets stay on the
backend. The frontend needs `NEXT_PUBLIC_API_BASE_URL`, and optionally `API_BASE_URL` for server-side
rendering and the production proxy (see `frontend/.env.example`).

## Troubleshooting

- **First visit to a page is slow in `npm run dev`.** Next compiles each route on first request; later loads
  take tens of milliseconds. `npm run build && npm start` shows production speed.
- **Every request is ~200 ms slower than it should be on Windows.** Use `127.0.0.1` rather than `localhost`
  for the backend; server-side fetches already default to 127.0.0.1 for this reason.
- **"n/a" prices on a page.** The provider is rate-limited or doesn't cover that market on its free tier; the
  page says which.

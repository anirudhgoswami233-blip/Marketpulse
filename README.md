# MarketPulse

A global stock market web app: live quotes, a markets overview, forex and metals, a macro dashboard, earnings
and IPO calendars, watchlists, paper trading, and a personalised **Daily Market Brief** built from technical
signals.

> Signals are educational information based on technical indicators, not financial advice. Paper trading uses
> virtual money.

- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2 (async) + Alembic, APScheduler, httpx. SQLite in dev,
  PostgreSQL in production. Redis for the shared cache and rate limiter (in-memory fallback in dev).
- **Frontend:** Next.js 16 (App Router, Cache Components), TypeScript strict, Tailwind CSS v4, TradingView
  Lightweight Charts.
- **Data:** Finnhub (primary, free tier), Twelve Data (price history, forex and metals), FRED (macro).

## Quick start

Requires Python 3.12 and Node 20+. Docker is optional.

### 1. Get the API keys (all free)

| Variable | Where to get it | Used for |
|---|---|---|
| `FINNHUB_API_KEY` | Sign up at [finnhub.io](https://finnhub.io/register). The key is on your [dashboard](https://finnhub.io/dashboard). | US quotes, live trades (WebSocket), profiles, metrics, news, market status, earnings/IPO calendars |
| `TWELVEDATA_API_KEY` | Sign up at [twelvedata.com](https://twelvedata.com/pricing) (Basic plan). The key is under *API Keys*. | Daily price history (charts and signals), forex pairs, gold |
| `FRED_API_KEY` | [Request a key](https://fred.stlouisfed.org/docs/api/api_key.html) with a free FRED account. | Macro dashboard (rates, inflation, unemployment, …) |

The app runs with any of them missing. The affected widgets then say that the provider isn't configured.

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

Optional: `.venv/Scripts/python scripts/check_finnhub_endpoints.py` re-checks which Finnhub endpoints your
key can use and rewrites `docs/finnhub-endpoints.md`.

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

Then set `DATABASE_URL` and `REDIS_URL` in `backend/.env` (see the comments in `docker-compose.yml`) and run
`alembic upgrade head` again. **Redis is required outside dev** (`ENV` other than `dev`). Without it, each
backend process would keep its own rate-limit counters and overspend the shared vendor quotas.

## Checks

```bash
# backend
cd backend && .venv/Scripts/ruff format . && .venv/Scripts/ruff check . && .venv/Scripts/mypy app scripts tests
cd backend && .venv/Scripts/pytest -q
# frontend
cd frontend && npm run lint && npm run typecheck && npm test
cd frontend && npm run build    # also enforces Cache Components rules
```

The test suites never call the real APIs: Finnhub, Twelve Data and FRED are mocked (respx on the backend,
a fetch stub on the frontend).

## How the free tiers are respected

Every external call goes through **provider adapter → rate limiter → cache**. Services ask the provider
registry for a capability ("quotes for this exchange", "daily history") and never name a vendor.

| Provider | Vendor limit | App limiter | Notes |
|---|---|---|---|
| Finnhub | ~60/min | **50/min** | One shared backend WebSocket for live trades |
| Twelve Data | 8/min, 800/day | **7/min, 750/day** | History cached 24h; forex/metal quotes 5 min |
| FRED | 120/min | 100/min | Macro series cached |

- **Priorities.** User requests are *interactive*: they wait up to 30 s for a slot, then get cached or stale
  data. Scheduled jobs are *background*: they may use only 70% of each per-minute budget and queue patiently,
  so a brief run never starves a page.
- **Caching** (Redis, or in-memory in dev): quotes 60 s, news 15 min, profiles/metrics 24 h, symbol lists 7 d,
  market status 5 min. When a provider fails or rate-limits, the last good value is served with its `as_of`
  time and a "stale" flag, and the UI shows "data as of HH:MM". Pages never crash on provider errors.
- **Live prices.** One backend WebSocket to Finnhub, subscribed only to symbols someone is viewing or watching
  (reference-counted), fanned out to browsers over one SSE stream per page. The key never reaches the
  browser.
- **Search** hits the seeded symbol directory in the database, not the API.
- **Daily Brief jobs** fetch each symbol once for all users and spread calls over time at background priority.

### Free-tier gaps and how the app handles them

- No Finnhub candles → price history comes from Twelve Data.
- No index quotes (`^GSPC`) or non-US quotes on either free tier → global indices appear as US-listed **ETF
  proxies** (SPY, EWJ, INDA, VGK, …), labelled as ETFs. Non-US stocks are searchable, but their pages explain
  that no price is available, and they can't be paper-traded.
- No Finnhub forex quotes → forex pairs and gold come from Twelve Data. Crosses are derived from USD pairs.
  Silver, platinum and palladium aren't on Twelve Data's free plan and are shown with that explanation.
- No news-sentiment endpoint → news tone is a keyword score over recent headlines.

## Features

- **Markets overview:** regional ETF proxies, market open/closed status, top movers, sector heatmap.
- **Stock pages:** live price, chart (1D–5Y), key stats, company news, a technical signal with reasons.
- **Forex & metals:** major and INR pairs, gold, a currency converter.
- **Macro:** FRED series with mini charts. **Calendar:** earnings and IPOs by week, defaulting to the current
  week in your timezone (profile, or the browser when signed out).
- **Accounts:** email + password (argon2). Short-lived JWT access tokens, rotating httpOnly refresh cookie with
  reuse detection.
- **Watchlists** with live prices. **Paper trading:** market orders against the latest quote, `Decimal` P&L,
  multi-currency positions converted to your base currency.
- **Daily Market Brief:** generated at your local brief time (optionally emailed via SMTP). It covers
  overnight markets, plus a signal per watchlist symbol: a label such as "Bullish signals" with the reasons
  behind it (RSI, MACD, moving averages, volume, 52-week range, news tone), never a bare buy/sell.
- **Signal History:** every generated signal is stored and later scored at 1, 5 and 20 trading days, so you
  can see how past readings played out.

## Project layout

```
backend/app/
  api/        thin FastAPI routers
  core/       config, security, logging, rate limiter, cache
  providers/  finnhub.py, fred.py, fallback/twelvedata.py, registry.py
  services/   business logic (markets, forex, portfolio, brief, …)
  signals/    pure indicator math and scoring
  jobs/       APScheduler jobs (market snapshot, daily brief, signal outcomes, forex)
  ws/         shared Finnhub WebSocket + fan-out
frontend/
  app/        routes · components/ UI · lib/ API client, hooks, formatters · types/
docs/         finnhub-endpoints.md (free-tier check), progress.md (phase notes and decisions)
```

## Configuration

All settings live in `backend/.env`; every variable is listed with comments in `backend/.env.example`. Secrets
stay on the backend. The frontend only needs `NEXT_PUBLIC_API_BASE_URL`, and optionally `API_BASE_URL` for
server-side rendering (see `frontend/.env.example`).

## Troubleshooting

- **First visit to a page is slow in `npm run dev`.** Next compiles each route on first request. Later loads
  take tens of milliseconds. `npm run build && npm start` shows production speed.
- **Every request is ~200 ms slower than it should be on Windows.** Use `127.0.0.1` rather than `localhost`
  for the backend. Server-side fetches already default to 127.0.0.1 for this reason.
- **"n/a" prices on a page.** The provider is rate-limited or doesn't cover that market on its free tier. The
  page says which.

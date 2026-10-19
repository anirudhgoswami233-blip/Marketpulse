# Deploying MarketPulse

Everything runs on free tiers:

| Piece | Host | Notes |
|---|---|---|
| Frontend (Next.js) | **Vercel** (Hobby) | Proxies `/api/v1/*` to the backend, so the sign-in cookie is first-party |
| Backend (FastAPI) | **Render** free web service | Sleeps after ~15 idle minutes; runs migrations on every start |
| PostgreSQL | **Neon** (Free) | Scales to zero when idle and wakes on connect |
| Redis (cache + rate limiter) | **Upstash** (Free) | Required outside dev, so every process shares one rate limiter |
| Daily jobs while Render sleeps | **GitHub Actions** schedule | Hourly call to a secret-protected jobs endpoint |

```
browser ──► https://<app>.vercel.app ── pages (SSR) ───────────────┐
   │              └─ /api/v1/* (rewrite proxy) ───────────────────►│
   └─ live prices (SSE, direct) ──────────────────────────────────►├─► https://<api>.onrender.com ─► Neon (Postgres)
GitHub Actions (hourly) ── POST /api/v1/internal/jobs/run ────────►│                              └► Upstash (Redis)
                                                                   └─► Finnhub · Twelve Data · FRED
```

**Why the proxy:** the refresh token is an httpOnly `SameSite=Lax` cookie. `*.vercel.app` and `*.onrender.com`
are different sites, so a browser would never send that cookie on a direct call to Render, and every page
reload would sign the user out. Through the proxy the browser only talks to the Vercel domain. Live-price
streams skip the proxy and go straight to Render (CORS allows the Vercel origin). They need no cookie, and a
proxy isn't meant to hold long-lived streams.

---

## 0. Before you start

- The repo is on GitHub (Render and Vercel deploy from it, and the scheduled workflow runs there). Push `main`.
- You have the three data API keys from the [README](README.md#1-get-the-api-keys-all-free).
  **Use the same keys only if your local dev server is stopped or quiet.** The vendors count calls per key,
  and your laptop's limiter doesn't share counts with production's Redis. Separate free keys for production
  are the safest choice. Finnhub also allows **only one WebSocket per key**: if you share the key, set
  `ENABLE_STREAMING=false` in your local `backend/.env`, or live prices on one side will keep disconnecting.
- Have a password manager or scratch note open: you'll copy a few URLs and secrets between dashboards.
  Never commit them.

Pick regions close together. For example, Render *Oregon*, Neon *AWS US West 2 (Oregon)* and Upstash
*us-west-2*, or Frankfurt for all three. Every request crosses between them.

## 1. Neon (PostgreSQL)

1. Sign up at [neon.tech](https://neon.tech) and **create a project** (Postgres 17, your chosen region). The
   default database `neondb` is fine.
2. On the project dashboard, click **Connect**. **Turn "Connection pooling" off** and copy the connection
   string. It looks like
   `postgresql://neondb_owner:…@ep-xxxx.us-west-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require`.
   - Use the *direct* (non-pooled) host, without `-pooler` in it. The pooler runs PgBouncer in transaction
     mode, which conflicts with the asyncpg driver's prepared statements. One small server doesn't need
     pooling.
   - Paste the string exactly as shown. The backend rewrites `postgresql://…?sslmode=require` into the
     `postgresql+asyncpg://…?ssl=require` form that asyncpg needs and drops `channel_binding`.
3. This is **`DATABASE_URL`**.

## 2. Upstash (Redis)

1. Sign up at [upstash.com](https://upstash.com), then **Redis → Create database**. Pick the region near
   Render, the free plan, and leave eviction **off**: rate-limit counters must not be evicted.
2. On the database page, under **Connect**, choose the **redis-cli / TCP** connection (not the REST API) and copy
   the URL. It starts with **`rediss://`** (two s's: TLS), e.g.
   `rediss://default:AbC…@usw2-xxxx.upstash.io:6379`.
3. This is **`REDIS_URL`**.

## 3. Render (backend)

1. Sign up at [render.com](https://render.com) with GitHub, then **New → Blueprint** and pick this repository.
   Render reads [`render.yaml`](render.yaml) and proposes the `marketpulse-api` free web service.
2. It asks for every variable marked `sync: false`. Fill them in:

   | Variable | Value |
   |---|---|
   | `DATABASE_URL` | Neon connection string from step 1 |
   | `REDIS_URL` | Upstash `rediss://` URL from step 2 |
   | `FINNHUB_API_KEY` | Your Finnhub key |
   | `TWELVEDATA_API_KEY` | Your Twelve Data key |
   | `FRED_API_KEY` | Your FRED key |
   | `CORS_ORIGINS` | `["https://placeholder.invalid"]` for now. Set the real Vercel URL in step 5 |
   | `CORS_ORIGIN_REGEX` | Leave empty for now (see step 5) |

3. **Apply**. The first build installs the requirements. Then the start command runs
   `alembic upgrade head`, which creates all tables in Neon, and starts uvicorn. Watch the **Logs** tab for
   `Running upgrade … -> bd29f1eaff82` and then `Application startup complete`.
4. Copy the service URL, e.g. `https://marketpulse-api.onrender.com`. Check:
   - `https://marketpulse-api.onrender.com/health` returns `{"status":"ok"}`
   - `https://marketpulse-api.onrender.com/api/v1/system/status` shows `"cache_backend": "redis"` and all three
     providers `"configured": true`. No key values are ever shown.

### Seed the symbol directory (once)

Search reads symbols from the database, so seed Neon once from your machine. It uses a handful of Finnhub
calls. In `backend/`, with the production `DATABASE_URL` set only for this one command:

```bash
# Git Bash / macOS / Linux
DATABASE_URL='postgresql://neondb_owner:…@ep-xxxx…/neondb?sslmode=require' .venv/Scripts/python scripts/seed_symbols.py
```
```powershell
# PowerShell
$env:DATABASE_URL = 'postgresql://neondb_owner:…@ep-xxxx…/neondb?sslmode=require'
.venv\Scripts\python scripts\seed_symbols.py
Remove-Item Env:DATABASE_URL
```

Searching "apple" on the deployed site should then find AAPL.

## 4. Vercel (frontend)

1. Sign up at [vercel.com](https://vercel.com) with GitHub, then **Add New → Project** and import this
   repository.
2. **Root Directory: `frontend`**. The framework preset is detected as Next.js, and the default build settings
   are right.
3. **Environment Variables**, for *Production* and *Preview*:

   | Variable | Value | Why |
   |---|---|---|
   | `NEXT_PUBLIC_API_BASE_URL` | `/` | The browser calls this site's own `/api/v1/*` (proxied) |
   | `API_BASE_URL` | `https://marketpulse-api.onrender.com` | Proxy target, and the backend for server-side rendering |
   | `NEXT_PUBLIC_STREAM_BASE_URL` | `https://marketpulse-api.onrender.com` | Live-price streams connect directly |

   None of these are secrets. Never add API keys to Vercel: the frontend doesn't need them.
   `NEXT_PUBLIC_*` values and the proxy target are baked in at build time, so **redeploy after changing
   them**.
4. **Deploy**, then note the production domain, e.g. `https://marketpulse.vercel.app`.

## 5. Allow the Vercel domain on the backend

In Render → `marketpulse-api` → **Environment**:

| Variable | Value |
|---|---|
| `CORS_ORIGINS` | `["https://marketpulse.vercel.app"]`, a JSON list: exact origins, no trailing slash. Add your custom domain here too if you attach one |
| `CORS_ORIGIN_REGEX` | Optional, for preview deployments: `^https://marketpulse-[a-z0-9-]+-<your-vercel-scope>\.vercel\.app$` |

Save. Render restarts the service with the new values. This list is used twice:

- **CORS**, for the direct live-price stream.
- **The auth endpoints' Origin check.** Refresh and sign-out refuse requests from any other site.

Preview deployments share the production backend and database, so only enable the regex if that's fine for
you.

## 6. GitHub Actions (scheduled jobs)

Render's free instance sleeps when idle, and the in-process scheduler sleeps with it.
[`.github/workflows/scheduled-jobs.yml`](.github/workflows/scheduled-jobs.yml) runs at minute 5 of every hour,
Sunday to Friday (UTC). Each run:

- wakes the API;
- calls `POST /api/v1/internal/jobs/run`, which starts the Daily Brief and signal-outcome jobs in the
  background;
- polls `GET /api/v1/internal/jobs` until they finish. The run fails, visibly, if a job failed.

Briefs are only built for users whose local brief time has passed and who don't have today's brief yet, so
extra runs are harmless.

1. In Render → Environment, reveal and copy **`CRON_SECRET`** (generated by the Blueprint).
2. In GitHub → repository → **Settings → Secrets and variables → Actions → New repository secret**:

   | Secret | Value |
   |---|---|
   | `MARKETPULSE_API_URL` | `https://marketpulse-api.onrender.com` |
   | `CRON_SECRET` | The value from Render |

3. **Actions → Scheduled jobs → Run workflow** to try it now. The log ends with one line per job:
   `daily_brief: running=False … error=None`.

Scheduled workflows only run on the default branch. GitHub may delay them by several minutes at busy times.
In public repos, it pauses them after 60 days without repository activity (re-enable them on the Actions
tab).

## 7. Smoke test

1. Open the Vercel URL. The first request after a quiet spell can take ~30–60 s while Render wakes up.
2. Markets overview, a stock page (`/stock/AAPL`) with a moving live price during US market hours, Forex,
   Macro, Calendar.
3. Register, then **reload the page: you should stay signed in.** This confirms the proxied cookie works.
   Sign out and back in.
4. Add a symbol to a watchlist, place a paper trade, open the Brief and generate it.
5. Run the GitHub workflow manually and check that it passes.

---

## Environment variable reference

### Render (backend)

| Variable | Required | Set by | Value / notes |
|---|---|---|---|
| `ENV` | yes | render.yaml | `production`. Anything but `dev` enforces `JWT_SECRET` and `REDIS_URL` |
| `PYTHON_VERSION` | yes | render.yaml | `3.12.10` |
| `DATABASE_URL` | yes | you | Neon direct connection string |
| `REDIS_URL` | yes | you | Upstash `rediss://…` URL. The server refuses to start without it outside dev |
| `JWT_SECRET` | yes | render.yaml (`generateValue`) | ≥ 32 chars. Rotating it signs everyone out |
| `CRON_SECRET` | for jobs | render.yaml (`generateValue`) | Bearer token for `/api/v1/internal/jobs*`. Empty disables those endpoints (404) |
| `COOKIE_SECURE` | yes | render.yaml | `true` (HTTPS only) |
| `CORS_ORIGINS` | yes | you | JSON list of frontend origins, e.g. `["https://marketpulse.vercel.app"]` |
| `CORS_ORIGIN_REGEX` | no | you | Extra allowed origins, e.g. Vercel previews |
| `FINNHUB_API_KEY` | yes | you | Quotes, live trades, profiles, news, calendars |
| `TWELVEDATA_API_KEY` | yes | you | Charts/indicators, forex, gold |
| `FRED_API_KEY` | for Macro | you | Macro dashboard |
| `OVERVIEW_REFRESH_OPEN_S` / `OVERVIEW_REFRESH_CLOSED_S` | no | render.yaml | `600` / `3600`. Overview snapshot cadence (keeps Upstash usage low) |
| `LOG_LEVEL` | no | — | Default `INFO` |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | no | you | Emailed briefs. Render's free instances block outbound SMTP ports (at the time of writing), so emailed briefs need a paid instance or a provider on another port |
| `LLM_API_KEY` | no | — | Unused for now (the brief text is templated) |

Other tuning variables (rate limits, limiter waits, watchlist caps) are listed with their defaults in
`backend/.env.example` and `backend/app/core/config.py`. The defaults are right for the free tiers.

### Vercel (frontend)

| Variable | Required | Value |
|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | yes | `/` |
| `API_BASE_URL` | yes | Render service URL |
| `NEXT_PUBLIC_STREAM_BASE_URL` | yes | Render service URL |

### GitHub Actions secrets

| Secret | Value |
|---|---|
| `MARKETPULSE_API_URL` | Render service URL |
| `CRON_SECRET` | Same value as on Render |

---

## Free-tier limits worth knowing

- **Render free:** 750 instance hours a month per workspace, enough for one service running all month.
  - **Sleep and cold starts:** the instance sleeps after 15 minutes without inbound requests. A cold start takes
    ~30–60 s, and the first visitor waits for it.
  - **Live prices:** while asleep there are none, and the shared Finnhub WebSocket reconnects on wake.
  - **No shell or pre-deploy command**, which is why migrations run in the start command and seeding runs
    from your machine.
- **Neon free:** 0.5 GB storage and a monthly compute allowance; it suspends after 5 idle minutes. The first
  query after that takes a moment longer. The connection pool pings before use, so stale connections are
  replaced.
- **Upstash free:** a monthly command quota (500K at the time of writing; check their pricing page). Each
  uncached provider call costs about 4 Redis commands, and a cache hit costs 1.
  - **Overview snapshot:** about 55 quotes per refresh. At the 10-minute open / 60-minute closed cadence set
    in render.yaml, plus the hourly forex board, that's roughly 300–350K commands a month if the server never
    slept. It sleeps much of the
    time, but heavy traffic adds up.
  - **Watching usage:** check Upstash's dashboard in the first week. If usage climbs, raise
    `OVERVIEW_REFRESH_OPEN_S`.
- **GitHub Actions:** free and unlimited for public repos. Private repos get 2,000 minutes a month, and each
  hourly run bills 1–3 minutes (~600–1,500 a month). To save minutes, change the cron to every 2 hours. To get
  briefs closer to the minute on a public repo, use `*/30`.
- **Data vendors** are unchanged: Finnhub 50/min, and Twelve Data 7/min and 750/day per key. Production's
  limiter lives in Redis, so restarts and redeploys don't reset the daily Twelve Data count.

## Security notes

- Secrets live only in Render's environment and GitHub's encrypted secrets. Vercel holds none.
- `CRON_SECRET` is compared in constant time. If it's unset, the jobs endpoints return 404. To rotate it,
  change it in Render and in the GitHub secret together.
- Job status only reports a failure's exception type. Details stay in the Render logs.
- **Login lockout and client IPs:** the lockout is keyed by email and client IP, and the IP is taken from
  `X-Forwarded-For` (`--proxy-headers`). That's needed because all proxied traffic arrives from Vercel.
  Someone calling the Render URL directly can forge that header, so treat the lockout as a speed bump.
  Passwords are argon2-hashed.

## Updating and rolling back

- **Deploys:** pushing to `main` redeploys both sites. Render runs any new migrations before the new version
  serves traffic. If a migration fails, uvicorn never starts, the new instance fails its health check, and the deploy is
  marked failed while the previous version keeps serving.
- **Rolling back code:** use Render → Deploys → *Rollback*, and Vercel → Deployments → *Promote*. A rollback
  doesn't undo migrations. Write schema changes so the previous version still works (add columns before
  using them), or restore a Neon branch/point-in-time snapshot.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Render log: `REDIS_URL must be set outside development` | `REDIS_URL` missing or empty |
| Render log: `JWT_SECRET must be at least 32 characters` | Secret too short or missing |
| `asyncpg … prepared statement … does not exist` | Pooled Neon URL (`-pooler` host). Use the direct one |
| Signed out on every reload | `NEXT_PUBLIC_API_BASE_URL` isn't `/`, or Vercel wasn't redeployed after setting it |
| `Request origin not allowed.` on sign-in refresh | The Vercel origin is missing from `CORS_ORIGINS` (exact match, no trailing slash) |
| Live prices never update | `NEXT_PUBLIC_STREAM_BASE_URL` missing, or the origin not in `CORS_ORIGINS` |
| Render log: `Finnhub WS … reconnecting in …s` over and over, with short or no connected time | Another process holds the key's single Finnhub WebSocket: a local dev server with streaming on, a second worker, or (briefly) the old instance during a deploy. The log line gives the HTTP status or close code; 401/403 means the key itself is rejected |
| Pages error with `API_BASE_URL must be set` | Set `API_BASE_URL` on Vercel and redeploy |
| Workflow fails with 401 | `CRON_SECRET` differs between GitHub and Render |
| Workflow fails with 404 | `CRON_SECRET` is empty on Render |
| Search finds nothing | The symbol directory wasn't seeded (step 3) |

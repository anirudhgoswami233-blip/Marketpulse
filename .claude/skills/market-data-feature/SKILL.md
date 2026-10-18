---
name: market-data-feature
description: Use when adding or changing any MarketPulse feature that uses market data — a new Finnhub endpoint, a page or widget showing quotes/news/fundamentals, a technical indicator, or the Daily Brief signal engine.
---

# Building market-data features in MarketPulse

Follow these steps in order whenever a feature touches market data. Read `CLAUDE.md` first if you haven't this session.

## Step 1 — Confirm the endpoint is available
1. Open `docs/finnhub-endpoints.md` and confirm the endpoint works on the free tier.
2. If it's missing or marked premium, run `python scripts/check_finnhub_endpoints.py` to re-check.
3. If it's still blocked: stop and tell the user. Propose a free fallback provider, and wait for approval before adding it.

## Step 2 — Add it to the provider layer
1. Add an abstract method to `providers/base.py` (`MarketDataProvider`) with typed Pydantic return models. Name it by what it returns, not by the vendor (`get_company_news`, not `finnhub_news`).
2. Implement it in `providers/finnhub.py`:
   - Wrap the call with `@rate_limited` and `@cached(ttl=...)`.
   - Map Finnhub's raw JSON into our Pydantic models. Never leak raw vendor fields past the adapter.
   - Handle errors: 429 → back off and retry once; 403 → raise `ProviderUnavailable`; network errors → raise `ProviderError`.
3. Pick the TTL from the table:

| Data | TTL |
|---|---|
| Quote | 60s |
| Market status | 5 min |
| News | 15 min |
| Profile, metrics, financials | 24h |
| Symbol lists | 7 days |
| Earnings/IPO calendar | 6h |

## Step 3 — Service and API
1. Put logic in `services/<area>_service.py`. Services call the provider interface, never `httpx` directly.
2. Return `{ data, as_of, source, stale: bool }` so the UI can show freshness.
3. Add a thin router in `api/` with a Pydantic response model.

## Step 4 — Frontend
1. Add typed fetchers in `frontend/lib/api.ts` and types in `frontend/types/`.
2. Every component must render: loading skeleton, empty state, error state with retry, and "Data as of HH:MM" when `stale` is true.
3. Live prices come from our backend WebSocket/SSE stream. Never open a Finnhub socket from the browser.
4. Format numbers with `Intl.NumberFormat` using the instrument's currency. Show times in the user's timezone, labelled with the exchange's market session.

## Step 5 — Live prices (WebSocket)
- Use the shared client in `ws/finnhub_stream.py`. Call `subscribe(symbol)` / `unsubscribe(symbol)` through the reference-counted subscription manager.
- On disconnect: reconnect with exponential backoff (1s, 2s, 4s… max 60s) and resubscribe to active symbols.
- Throttle fan-out to clients to at most one update per symbol per second.

## Step 6 — Indicators and the signal engine
All indicator code lives in `signals/` as **pure functions** over a list of OHLCV bars. No I/O.

Standard definitions (use these exactly so results are consistent and testable):
- **SMA(n):** mean of last n closes.
- **EMA(n):** α = 2/(n+1), seeded with SMA(n).
- **RSI(14):** Wilder's smoothing. < 30 oversold, > 70 overbought.
- **MACD:** EMA(12) − EMA(26); signal = EMA(9) of MACD; crossover = sign change of (MACD − signal).
- **Trend:** close vs SMA(50) and SMA(200); golden/death cross = SMA(50) crossing SMA(200).
- **Volume spike:** today's volume > 2× 20-day average volume.
- **52-week proximity:** within 3% of the 52-week high or low.

Scoring:
1. Each rule returns `Signal(name, direction: +1/0/−1, weight, reason: str)`.
2. Score = weighted sum, normalised to −100…+100.
3. Labels: ≥ +30 "Bullish signals", ≤ −30 "Bearish signals", otherwise "Neutral".
4. Always return the list of reasons with the label. A label without reasons is a bug.
5. If there's not enough history for an indicator (e.g. < 200 bars for SMA200), skip that rule and say so in the reasons. Never fill in fake values.
6. Persist every generated signal (symbol, date, score, label, reasons, price at signal) for the Signal History page.

## Step 7 — Daily Brief job
- Lives in `jobs/daily_brief.py`, scheduled per user timezone.
- Collect the set of unique symbols across all users due for a brief, fetch each once, then build every user's brief from the shared results.
- Spread fetches over time through the rate limiter. A brief run must never exceed 50 calls/min.
- If `LLM_API_KEY` is set, use the LLM only to *rewrite* the computed signals into prose. It must not invent numbers or signals. Without the key, use the templates in `jobs/templates/`.
- Always append: *"Educational information based on technical indicators, not financial advice."*

## Step 8 — Tests (required before finishing)
- **Provider:** mock HTTP responses (`respx`) for success, 429, 403, and malformed JSON.
- **Signals:** fixed OHLCV fixtures with known expected RSI/MACD/SMA values, plus edge cases (short history, flat prices, gaps).
- **Rate limiter:** confirm bursts get queued and never exceed the limit.
- **Brief:** confirm the disclaimer is present and each label has reasons.
- **Frontend:** test the loading, empty, error and stale states.
- Never call the real Finnhub API in tests.

## Done checklist
- [ ] Endpoint confirmed free-tier available
- [ ] Goes through provider → rate limiter → cache
- [ ] No API key reachable from the frontend or logs
- [ ] UI has loading / empty / error / stale states
- [ ] Tests added and passing; lint and typecheck clean
- [ ] `.env.example` and `CLAUDE.md` updated if anything changed
- [ ] Summarised to the user what changed and what to test manually

# MarketPulse frontend

Next.js (App Router, Cache Components) + TypeScript + Tailwind, with TradingView Lightweight Charts.

```bash
cp .env.example .env.local   # point NEXT_PUBLIC_API_BASE_URL at the backend
npm install
npm run dev                  # http://localhost:3000 (backend must be running on :8000)
npm run lint && npm run typecheck && npm test
```

The browser talks only to our FastAPI backend: REST for data and one Server-Sent Events stream per page
for live prices. No provider API keys exist in this app. See the repo-level `CLAUDE.md` for the full guide.

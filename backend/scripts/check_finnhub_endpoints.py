"""Probe Finnhub endpoints with the configured key and report free-tier availability.

Usage (from backend/):
    .venv/Scripts/python scripts/check_finnhub_endpoints.py

Writes docs/finnhub-endpoints.md at the repo root. The API key is read from backend/.env,
sent only in the X-Finnhub-Token header (or the WebSocket URL, which is never printed),
and scrubbed from any error text.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import websockets
from dotenv import dotenv_values

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
OUTPUT_PATH = REPO_ROOT / "docs" / "finnhub-endpoints.md"

REST_BASE = "https://finnhub.io/api/v1"
WS_URL = "wss://ws.finnhub.io"
FRED_BASE = "https://api.stlouisfed.org/fred"
CALL_SPACING_S = 1.5
WS_WAIT_S = 15.0


@dataclass
class Probe:
    group: str
    name: str
    path: str
    params: dict[str, str | int]


@dataclass
class Result:
    group: str
    name: str
    endpoint: str
    status: str
    http_status: int | None
    latency_ms: int | None
    shape: str
    note: str = ""

    @property
    def works(self) -> str:
        return {"OK": "yes", "EMPTY": "partial", "PREMIUM": "no", "RATE_LIMITED": "?", "ERROR": "no"}[
            self.status
        ]


def load_env() -> dict[str, str]:
    raw = dotenv_values(BACKEND_DIR / ".env")
    return {k.strip(): (v or "").strip() for k, v in raw.items()}


def build_probes() -> list[Probe]:
    today = date.today()
    now = int(datetime.now(UTC).timestamp())
    year_ago = now - 365 * 86400
    return [
        Probe("Quotes", "Quote US stock (AAPL)", "/quote", {"symbol": "AAPL"}),
        Probe("Quotes", "Quote India (RELIANCE.NS)", "/quote", {"symbol": "RELIANCE.NS"}),
        Probe("Quotes", "Quote London (VOD.L)", "/quote", {"symbol": "VOD.L"}),
        Probe("Quotes", "Quote index (^GSPC)", "/quote", {"symbol": "^GSPC"}),
        Probe("Quotes", "Quote ETF (SPY)", "/quote", {"symbol": "SPY"}),
        Probe("Quotes", "Quote crypto (BINANCE:BTCUSDT)", "/quote", {"symbol": "BINANCE:BTCUSDT"}),
        Probe(
            "Candles",
            "Stock candles daily 1Y (AAPL)",
            "/stock/candle",
            {"symbol": "AAPL", "resolution": "D", "from": year_ago, "to": now},
        ),
        Probe(
            "Candles",
            "Forex candles daily 1Y",
            "/forex/candle",
            {"symbol": "OANDA:EUR_USD", "resolution": "D", "from": year_ago, "to": now},
        ),
        Probe("Symbols", "Symbol search", "/search", {"q": "apple"}),
        Probe("Symbols", "Symbol list US", "/stock/symbol", {"exchange": "US"}),
        Probe("Symbols", "Symbol list India (NS)", "/stock/symbol", {"exchange": "NS"}),
        Probe("Symbols", "Symbol list London (L)", "/stock/symbol", {"exchange": "L"}),
        Probe("Company", "Company profile", "/stock/profile2", {"symbol": "AAPL"}),
        Probe("Company", "Basic financials / metrics", "/stock/metric", {"symbol": "AAPL", "metric": "all"}),
        Probe(
            "News",
            "Company news (7d)",
            "/company-news",
            {"symbol": "AAPL", "from": str(today - timedelta(days=7)), "to": str(today)},
        ),
        Probe("News", "General market news", "/news", {"category": "general"}),
        Probe("News", "News sentiment", "/news-sentiment", {"symbol": "AAPL"}),
        Probe(
            "Calendars",
            "Earnings calendar (14d)",
            "/calendar/earnings",
            {"from": str(today), "to": str(today + timedelta(days=14))},
        ),
        Probe(
            "Calendars",
            "IPO calendar (-30d..+30d)",
            "/calendar/ipo",
            {"from": str(today - timedelta(days=30)), "to": str(today + timedelta(days=30))},
        ),
        Probe("Forex", "Forex quote (OANDA:USD_INR)", "/quote", {"symbol": "OANDA:USD_INR"}),
        Probe("Forex", "Forex rates (base USD)", "/forex/rates", {"base": "USD"}),
        Probe("Forex", "Forex exchanges", "/forex/exchange", {}),
        Probe("Forex", "Forex symbols (oanda)", "/forex/symbol", {"exchange": "oanda"}),
        Probe("Market", "Market status (US)", "/stock/market-status", {"exchange": "US"}),
        Probe("Market", "Market holidays (US)", "/stock/market-holiday", {"exchange": "US"}),
        Probe("Market", "Index constituents (^GSPC)", "/index/constituents", {"symbol": "^GSPC"}),
    ]


def scrub(text: str, secrets: list[str]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return text


def describe_shape(payload: Any) -> str:
    if isinstance(payload, list):
        first = payload[0] if payload else None
        keys = ",".join(list(first.keys())[:8]) if isinstance(first, dict) else ""
        return f"list[{len(payload)}]" + (f", keys: {keys}" if keys else "")
    if isinstance(payload, dict):
        parts = []
        for key, value in list(payload.items())[:8]:
            if isinstance(value, list):
                parts.append(f"{key}[{len(value)}]")
            elif isinstance(value, dict):
                parts.append(f"{key}{{{len(value)}}}")
            else:
                parts.append(key)
        return "dict, keys: " + ",".join(parts)
    return type(payload).__name__


def is_empty(payload: Any) -> bool:
    if payload in (None, [], {}):
        return True
    if isinstance(payload, dict):
        # /quote returns zeros for unknown/unsupported symbols; candles return s="no_data"
        if payload.get("s") == "no_data":
            return True
        if set(payload) >= {"c", "pc"} and not payload.get("c") and not payload.get("pc"):
            return True
        # list-wrapping responses such as {"earningsCalendar": []} or {"result": []}
        values = list(payload.values())
        if len(values) == 1 and values[0] in ([], {}, None):
            return True
    return False


def endpoint_label(path: str, params: dict[str, str | int]) -> str:
    shown = {k: v for k, v in params.items() if k not in {"from", "to"}}
    query = "&".join(f"{k}={v}" for k, v in shown.items())
    return f"`{path}" + (f"?{query}" if query else "") + "`"


async def run_rest_probe(client: httpx.AsyncClient, probe: Probe, secrets: list[str]) -> Result:
    label = endpoint_label(probe.path, probe.params)
    started = time.perf_counter()
    try:
        # Large lists (e.g. /stock/symbol?exchange=US) 302 to a signed file on static2.finnhub.io
        response = await client.get(probe.path, params=probe.params, follow_redirects=True)
    except httpx.HTTPError as exc:
        return Result(probe.group, probe.name, label, "ERROR", None, None, "", scrub(repr(exc), secrets))
    latency = int((time.perf_counter() - started) * 1000)
    body_text = scrub(response.text[:200], secrets)

    if response.status_code in (401, 403):
        return Result(probe.group, probe.name, label, "PREMIUM", 403, latency, "", body_text)
    if response.status_code == 429:
        return Result(probe.group, probe.name, label, "RATE_LIMITED", 429, latency, "", body_text)
    if response.status_code >= 400:
        return Result(probe.group, probe.name, label, "ERROR", response.status_code, latency, "", body_text)

    try:
        payload = response.json()
    except json.JSONDecodeError:
        return Result(
            probe.group, probe.name, label, "ERROR", response.status_code, latency, "", "non-JSON body"
        )

    if isinstance(payload, dict) and "error" in payload:
        error = scrub(str(payload["error"]), secrets)
        status = "PREMIUM" if "access" in error.lower() or "premium" in error.lower() else "ERROR"
        return Result(probe.group, probe.name, label, status, response.status_code, latency, "", error)

    status = "EMPTY" if is_empty(payload) else "OK"
    note = "empty/zero payload: likely unsupported on free tier" if status == "EMPTY" else ""
    return Result(
        probe.group, probe.name, label, status, response.status_code, latency, describe_shape(payload), note
    )


async def run_ws_probe(api_key: str, secrets: list[str]) -> Result:
    symbols = ["AAPL", "BINANCE:BTCUSDT"]
    label = f"`{WS_URL}` (subscribe {', '.join(symbols)})"
    started = time.perf_counter()
    try:
        async with websockets.connect(f"{WS_URL}?token={api_key}", open_timeout=10) as ws:
            for symbol in symbols:
                await ws.send(json.dumps({"type": "subscribe", "symbol": symbol}))
            seen: dict[str, int] = {}
            deadline = time.perf_counter() + WS_WAIT_S
            while time.perf_counter() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=deadline - time.perf_counter())
                except TimeoutError:
                    break
                message = json.loads(raw)
                kind = message.get("type", "?")
                if kind == "trade":
                    for trade in message.get("data", []):
                        seen[trade.get("s", "?")] = seen.get(trade.get("s", "?"), 0) + 1
                    if "BINANCE:BTCUSDT" in seen:
                        break
                elif kind == "error":
                    msg = scrub(str(message.get("msg")), secrets)
                    return Result("Streaming", "WebSocket trades", label, "ERROR", None, None, "", msg)
            for symbol in symbols:
                await ws.send(json.dumps({"type": "unsubscribe", "symbol": symbol}))
    except Exception as exc:  # report any connect/handshake failure in the table
        return Result(
            "Streaming", "WebSocket trades", label, "ERROR", None, None, "", scrub(repr(exc), secrets)
        )

    latency = int((time.perf_counter() - started) * 1000)
    if not seen:
        return Result(
            "Streaming",
            "WebSocket trades",
            label,
            "EMPTY",
            None,
            latency,
            "",
            f"connected, no trades within {WS_WAIT_S:.0f}s",
        )
    counts = ", ".join(f"{s}: {n}" for s, n in seen.items())
    note = "" if "AAPL" in seen else "AAPL silent (US market likely closed)"
    return Result("Streaming", "WebSocket trades", label, "OK", None, latency, f"trades: {counts}", note)


async def run_fred_probe(fred_key: str, secrets: list[str]) -> Result:
    label = "`fred/series/observations?series_id=FEDFUNDS`"
    params: dict[str, str | int] = {
        "series_id": "FEDFUNDS",
        "api_key": fred_key,
        "file_type": "json",
        "limit": 5,
        "sort_order": "desc",
    }
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(base_url=FRED_BASE, timeout=15) as client:
            response = await client.get("/series/observations", params=params)
    except httpx.HTTPError as exc:
        return Result(
            "Macro (FRED)", "Fed funds rate", label, "ERROR", None, None, "", scrub(repr(exc), secrets)
        )
    latency = int((time.perf_counter() - started) * 1000)
    if response.status_code != 200:
        return Result(
            "Macro (FRED)",
            "Fed funds rate",
            label,
            "ERROR",
            response.status_code,
            latency,
            "",
            scrub(response.text[:200], secrets),
        )
    payload = response.json()
    observations = payload.get("observations", [])
    status = "OK" if observations else "EMPTY"
    return Result(
        "Macro (FRED)", "Fed funds rate", label, status, 200, latency, f"observations[{len(observations)}]"
    )


def write_markdown(results: list[Result]) -> None:
    generated = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Finnhub endpoint availability",
        "",
        f"Generated by `backend/scripts/check_finnhub_endpoints.py` on {generated}.",
        "Re-run the script to refresh. Check this file before using an endpoint (see CLAUDE.md).",
        "",
        "Legend: **yes** = works on our key · **partial** = 200 but empty/zero data · "
        "**no** = 403/premium or error",
        "",
        "| Group | Check | Endpoint | HTTP | Status | Free tier | Latency | Shape / notes |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        detail = " · ".join(part for part in (r.shape, r.note) if part).replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| {r.group} | {r.name} | {r.endpoint} | {r.http_status or '-'} | {r.status} | {r.works} | "
            f"{f'{r.latency_ms} ms' if r.latency_ms is not None else '-'} | {detail} |"
        )
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def main() -> int:
    env = load_env()
    api_key = env.get("FINNHUB_API_KEY", "")
    fred_key = env.get("FRED_API_KEY", "")
    if not api_key:
        print("FINNHUB_API_KEY is missing from backend/.env", file=sys.stderr)
        return 1
    secrets = [api_key, fred_key]

    results: list[Result] = []
    probes = build_probes()
    async with httpx.AsyncClient(
        base_url=REST_BASE, headers={"X-Finnhub-Token": api_key}, timeout=20
    ) as client:
        for index, probe in enumerate(probes, start=1):
            result = await run_rest_probe(client, probe, secrets)
            results.append(result)
            print(f"[{index:2}/{len(probes)}] {result.status:<12} {probe.name}")
            if result.status == "RATE_LIMITED":
                await asyncio.sleep(10)
            await asyncio.sleep(CALL_SPACING_S)

    print("[ws] probing WebSocket ...")
    results.append(await run_ws_probe(api_key, secrets))
    print(f"[ws] {results[-1].status}")

    if fred_key:
        results.append(await run_fred_probe(fred_key, secrets))
        print(f"[fred] {results[-1].status}")
    else:
        print("[fred] skipped: FRED_API_KEY not set")

    write_markdown(results)
    ok = sum(r.status == "OK" for r in results)
    print(f"\n{ok}/{len(results)} checks OK. Wrote {OUTPUT_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

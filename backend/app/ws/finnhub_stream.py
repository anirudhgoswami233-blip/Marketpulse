"""The single shared Finnhub WebSocket. Never opened from the browser (it would expose the key).

Subscriptions are reference-counted: a symbol is subscribed when the first viewer needs it and unsubscribed
when the last one leaves. On disconnect we reconnect with jittered exponential backoff (2s, 4s ... 5 min) and
resubscribe to everything still needed.

Finnhub allows one WebSocket per API key. When a second one connects (another worker, a local dev server, an
overlapping deploy), Finnhub accepts the socket and then drops it, or rejects the handshake with HTTP 429. So
the backoff only resets after a connection has stayed up for a while: a successful handshake alone proves
nothing.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import random
import time
from collections import Counter
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

import websockets
from websockets.exceptions import ConnectionClosed, InvalidStatus

from app.ws.hub import PriceHub, Trade

logger = logging.getLogger(__name__)

WS_URL = "wss://ws.finnhub.io"
BACKOFF_INITIAL_S = 2.0
BACKOFF_MAX_S = 300.0
# A connection resets the backoff only after staying up this long.
STABLE_AFTER_S = 60.0
# Handshake rejected with 429: wait at least this long (or the server's Retry-After, if longer).
RATE_LIMITED_MIN_S = 60.0
# 401/403: the key is wrong or revoked, so retrying soon can't help.
AUTH_FAILED_WAIT_S = 900.0
# After this many failed or short-lived connections in a row, log the likely cause.
CONTENTION_HINT_AFTER = 3


class WebSocketLike(Protocol):
    async def send(self, message: str) -> None: ...
    def __aiter__(self) -> AsyncIterator[str | bytes]: ...


Connector = Callable[[str], AbstractAsyncContextManager[WebSocketLike]]


def _default_connector(url: str) -> AbstractAsyncContextManager[WebSocketLike]:
    return websockets.connect(url, open_timeout=10, ping_interval=20)


class FinnhubStream:
    def __init__(
        self,
        api_key: str,
        hub: PriceHub,
        max_symbols: int = 50,
        connector: Connector = _default_connector,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
        jitter: Callable[[float, float], float] = random.uniform,
    ) -> None:
        self._url = f"{WS_URL}?token={api_key}"  # Finnhub only accepts the token here; never log this URL
        self._hub = hub
        self._max_symbols = max_symbols
        self._connector = connector
        self._sleep = sleep
        self._clock = clock
        self._jitter = jitter
        self._refs: Counter[str] = Counter()
        self._ws: WebSocketLike | None = None
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self.connected = asyncio.Event()

    @property
    def symbols(self) -> set[str]:
        return set(self._refs)

    async def acquire(self, symbol: str) -> bool:
        """Register interest in a symbol. Returns False when the connection's symbol cap is reached."""
        async with self._lock:
            if symbol not in self._refs:
                if len(self._refs) >= self._max_symbols:
                    return False
                await self._send({"type": "subscribe", "symbol": symbol})
            self._refs[symbol] += 1
            return True

    async def release(self, symbol: str) -> None:
        async with self._lock:
            if symbol not in self._refs:
                return
            self._refs[symbol] -= 1
            if self._refs[symbol] <= 0:
                del self._refs[symbol]
                await self._send({"type": "unsubscribe", "symbol": symbol})

    async def _send(self, message: dict[str, str]) -> None:
        if self._ws is None:
            return  # not connected: the reconnect loop resubscribes everything in _refs
        try:
            await self._ws.send(json.dumps(message))
        except Exception as exc:  # the receive loop notices the broken socket and reconnects
            logger.warning("Finnhub WS send failed (%s); will resync on reconnect", type(exc).__name__)

    async def run(self) -> None:
        failures = 0  # failed or short-lived connections in a row
        while True:
            connected_at: float | None = None
            floor = 0.0
            try:
                async with self._connector(self._url) as ws:
                    connected_at = self._clock()
                    async with self._lock:
                        self._ws = ws
                        for symbol in self._refs:
                            await ws.send(json.dumps({"type": "subscribe", "symbol": symbol}))
                    self.connected.set()
                    logger.info("Finnhub WS connected (%d symbols)", len(self._refs))
                    async for raw in ws:
                        self.handle_message(raw)
                reason = "closed by server"
            except asyncio.CancelledError:
                raise
            except InvalidStatus as exc:
                status = exc.response.status_code
                reason = f"handshake rejected with HTTP {status}"
                if status == 429:
                    floor = max(RATE_LIMITED_MIN_S, _retry_after_s(exc))
                elif status in (401, 403):
                    floor = AUTH_FAILED_WAIT_S
                    logger.error("Finnhub WS rejected the API key (HTTP %d); check FINNHUB_API_KEY", status)
            except ConnectionClosed as exc:
                reason = _describe_close(exc)
            except Exception as exc:
                # str(exc) can include the handshake URL with the token, so log only the type.
                reason = type(exc).__name__
            finally:
                self._ws = None
                self.connected.clear()

            uptime = self._clock() - connected_at if connected_at is not None else None
            failures = 0 if uptime is not None and uptime >= STABLE_AFTER_S else failures + 1
            delay = max(floor, self._backoff(failures))
            logger.warning(
                "Finnhub WS %s (%s); reconnecting in %.0fs, %d unstable attempts in a row",
                reason,
                "never connected" if uptime is None else f"was connected for {uptime:.0f}s",
                delay,
                failures,
            )
            if failures == CONTENTION_HINT_AFTER:
                logger.warning(
                    "Finnhub allows one WebSocket per API key. If this keeps happening, another process is "
                    "probably using FINNHUB_API_KEY: a second uvicorn worker, a local dev server with "
                    "streaming enabled, or an older instance during a deploy."
                )
            await self._sleep(delay)

    def _backoff(self, failures: int) -> float:
        """Jittered exponential backoff; at least half the nominal delay, so retries never bunch up at ~0s."""
        if failures == 0:
            return self._jitter(BACKOFF_INITIAL_S / 2, BACKOFF_INITIAL_S)
        nominal = min(BACKOFF_INITIAL_S * 2 ** (failures - 1), BACKOFF_MAX_S)
        return self._jitter(nominal / 2, nominal)

    def handle_message(self, raw: str | bytes) -> None:
        try:
            message: dict[str, Any] = json.loads(raw)
        except (ValueError, TypeError):
            logger.warning("Ignoring malformed Finnhub WS message")
            return
        kind = message.get("type")
        if kind == "trade":
            for item in message.get("data") or []:
                trade = _parse_trade(item)
                if trade is not None:
                    self._hub.publish(trade)
        elif kind == "error":
            logger.warning("Finnhub WS error message: %s", str(message.get("msg"))[:200])

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self.run(), name="finnhub-ws")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None


def _retry_after_s(exc: InvalidStatus) -> float:
    value = exc.response.headers.get("Retry-After", "")
    try:
        return max(float(value), 0.0)
    except ValueError:
        return 0.0


def _describe_close(exc: ConnectionClosed) -> str:
    """Close code and reason (never the URL). 1006 = dropped without a close frame."""
    frame = exc.rcvd or exc.sent
    if frame is None:
        return "connection dropped (no close frame)"
    reason = f": {frame.reason[:100]}" if frame.reason else ""
    side = "server" if exc.rcvd is not None else "client"
    return f"closed by {side} with code {frame.code}{reason}"


def _parse_trade(item: Any) -> Trade | None:
    if not isinstance(item, dict):
        return None
    symbol, price, ts = item.get("s"), item.get("p"), item.get("t")
    if not isinstance(symbol, str) or price is None or not isinstance(ts, int | float):
        return None
    try:
        volume = item.get("v")
        return Trade(
            symbol=symbol,
            price=Decimal(str(price)),
            timestamp=datetime.fromtimestamp(ts / 1000, tz=UTC),
            volume=Decimal(str(volume)) if volume is not None else None,
        )
    except (InvalidOperation, ValueError, OverflowError):
        return None

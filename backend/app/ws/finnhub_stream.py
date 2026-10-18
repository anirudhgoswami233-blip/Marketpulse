"""The single shared Finnhub WebSocket. Never opened from the browser (it would expose the key).

Subscriptions are reference-counted: a symbol is subscribed when the first viewer needs it and unsubscribed
when the last one leaves. On disconnect we reconnect with exponential backoff (1s, 2s, 4s ... 60s) and
resubscribe to everything still needed.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections import Counter
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

import websockets

from app.ws.hub import PriceHub, Trade

logger = logging.getLogger(__name__)

WS_URL = "wss://ws.finnhub.io"
BACKOFF_INITIAL_S = 1.0
BACKOFF_MAX_S = 60.0


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
    ) -> None:
        self._url = f"{WS_URL}?token={api_key}"  # Finnhub only accepts the token here; never log this URL
        self._hub = hub
        self._max_symbols = max_symbols
        self._connector = connector
        self._sleep = sleep
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
        backoff = BACKOFF_INITIAL_S
        while True:
            try:
                async with self._connector(self._url) as ws:
                    async with self._lock:
                        self._ws = ws
                        for symbol in self._refs:
                            await ws.send(json.dumps({"type": "subscribe", "symbol": symbol}))
                    self.connected.set()
                    logger.info("Finnhub WS connected (%d symbols)", len(self._refs))
                    backoff = BACKOFF_INITIAL_S
                    async for raw in ws:
                        self.handle_message(raw)
                logger.warning("Finnhub WS closed by server")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # str(exc) can include the handshake URL with the token, so log only the type.
                logger.warning("Finnhub WS error: %s", type(exc).__name__)
            finally:
                self._ws = None
                self.connected.clear()
            logger.info("Reconnecting Finnhub WS in %.0fs", backoff)
            await self._sleep(backoff)
            backoff = min(backoff * 2, BACKOFF_MAX_S)

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

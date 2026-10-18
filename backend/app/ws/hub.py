"""Fans live trades out to browser clients (SSE), at most one update per symbol per flush interval."""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

logger = logging.getLogger(__name__)

CLIENT_QUEUE_SIZE = 256


class Trade(BaseModel):
    symbol: str
    price: Decimal
    timestamp: datetime
    volume: Decimal | None = None


@dataclass(eq=False)
class HubClient:
    id: int
    symbols: frozenset[str]
    queue: asyncio.Queue[Trade] = field(default_factory=lambda: asyncio.Queue(maxsize=CLIENT_QUEUE_SIZE))
    dropped: int = 0


class PriceHub:
    def __init__(self, flush_interval_s: float = 1.0) -> None:
        self._flush_interval_s = flush_interval_s
        self._latest: dict[str, Trade] = {}
        self._dirty: set[str] = set()
        self._clients: dict[int, HubClient] = {}
        self._ids = itertools.count(1)
        self._task: asyncio.Task[None] | None = None

    def publish(self, trade: Trade) -> None:
        current = self._latest.get(trade.symbol)
        if current is not None and current.timestamp > trade.timestamp:
            return  # out-of-order trade
        self._latest[trade.symbol] = trade
        self._dirty.add(trade.symbol)

    def last_trade(self, symbol: str) -> Trade | None:
        return self._latest.get(symbol)

    def register(self, symbols: frozenset[str]) -> HubClient:
        client = HubClient(id=next(self._ids), symbols=symbols)
        self._clients[client.id] = client
        # Send the last known price straight away so the page doesn't wait for the next trade.
        for symbol in symbols:
            trade = self._latest.get(symbol)
            if trade is not None:
                client.queue.put_nowait(trade)
        return client

    def unregister(self, client: HubClient) -> None:
        self._clients.pop(client.id, None)

    def flush(self) -> int:
        """Push the latest trade for each symbol changed since the last flush. Returns messages queued."""
        if not self._dirty:
            return 0
        dirty, self._dirty = self._dirty, set()
        sent = 0
        for client in list(self._clients.values()):
            for symbol in client.symbols & dirty:
                try:
                    client.queue.put_nowait(self._latest[symbol])
                    sent += 1
                except asyncio.QueueFull:
                    client.dropped += 1  # slow client: skip rather than block everyone else
        return sent

    async def run(self) -> None:
        while True:
            await asyncio.sleep(self._flush_interval_s)
            self.flush()

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self.run(), name="price-hub-flush")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

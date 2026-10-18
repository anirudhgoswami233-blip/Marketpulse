import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal

import pytest

from app.ws.finnhub_stream import FinnhubStream
from app.ws.hub import PriceHub


class FakeSocket:
    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []
        self.incoming: asyncio.Queue[str | None] = asyncio.Queue()

    async def send(self, message: str) -> None:
        self.sent.append(json.loads(message))

    def __aiter__(self) -> AsyncIterator[str]:
        return self._iter()

    async def _iter(self) -> AsyncIterator[str]:
        while (item := await self.incoming.get()) is not None:
            yield item


class FakeConnector:
    """Hands out sockets in order; `fail_first` connection attempts raise before connecting."""

    def __init__(self, fail_first: int = 0) -> None:
        self.sockets: list[FakeSocket] = []
        self.urls: list[str] = []
        self.fail_first = fail_first
        self.ready = asyncio.Event()

    @asynccontextmanager
    async def __call__(self, url: str) -> AsyncIterator[FakeSocket]:
        self.urls.append(url)
        if self.fail_first > 0:
            self.fail_first -= 1
            raise OSError("connection refused")
        socket = FakeSocket()
        self.sockets.append(socket)
        self.ready.set()
        yield socket


async def test_reference_counted_subscriptions() -> None:
    stream = FinnhubStream("key", PriceHub(), connector=FakeConnector())
    socket = FakeSocket()
    stream._ws = socket  # simulate a live connection

    assert await stream.acquire("AAPL")
    assert await stream.acquire("AAPL")
    await stream.release("AAPL")
    assert socket.sent == [{"type": "subscribe", "symbol": "AAPL"}]  # still one viewer left
    await stream.release("AAPL")
    assert socket.sent[-1] == {"type": "unsubscribe", "symbol": "AAPL"}
    assert stream.symbols == set()


async def test_symbol_cap_is_enforced() -> None:
    stream = FinnhubStream("key", PriceHub(), max_symbols=2, connector=FakeConnector())
    assert await stream.acquire("A") and await stream.acquire("B")
    assert not await stream.acquire("C")
    assert await stream.acquire("A")  # existing symbols can gain viewers


async def test_reconnects_with_backoff_and_resubscribes() -> None:
    connector = FakeConnector(fail_first=2)
    sleeps: list[float] = []

    async def record_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        await asyncio.sleep(0)

    stream = FinnhubStream("secret-key", PriceHub(), connector=connector, sleep=record_sleep)
    await stream.acquire("AAPL")  # before connecting: queued, sent on connect
    task = asyncio.create_task(stream.run())
    await asyncio.wait_for(connector.ready.wait(), 1)
    await asyncio.wait_for(stream.connected.wait(), 1)

    assert sleeps == [1.0, 2.0]
    assert connector.sockets[0].sent == [{"type": "subscribe", "symbol": "AAPL"}]
    assert connector.urls[0].endswith("token=secret-key")

    # Server drops the connection: we reconnect and resubscribe.
    connector.ready.clear()
    await connector.sockets[0].incoming.put(None)
    await asyncio.wait_for(connector.ready.wait(), 1)
    await asyncio.sleep(0)
    assert connector.sockets[1].sent == [{"type": "subscribe", "symbol": "AAPL"}]
    assert sleeps[-1] == 1.0  # backoff reset after the successful connection

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_trade_messages_reach_the_hub() -> None:
    hub = PriceHub()
    stream = FinnhubStream("key", hub, connector=FakeConnector())
    stream.handle_message(
        json.dumps(
            {
                "type": "trade",
                "data": [
                    {"s": "AAPL", "p": 252.31, "t": 1792540800123, "v": 100},
                    {"s": "BAD"},  # missing fields: skipped
                ],
            }
        )
    )
    stream.handle_message("not json")
    stream.handle_message(json.dumps({"type": "ping"}))

    trade = hub.last_trade("AAPL")
    assert trade is not None
    assert trade.price == Decimal("252.31")
    assert trade.timestamp.microsecond == 123000
    assert hub.last_trade("BAD") is None

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal

import pytest
from websockets.datastructures import Headers
from websockets.exceptions import ConnectionClosedError, InvalidStatus
from websockets.frames import Close
from websockets.http11 import Response

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


class ScriptedConnector:
    """Each attempt follows the next step: "drop" connects then closes at once, an exception is raised at the
    handshake, and "hold" connects and stays open until the test closes it."""

    def __init__(self, steps: list[object], clock: "FakeClock") -> None:
        self.steps = steps
        self.clock = clock
        self.sockets: list[FakeSocket] = []
        self.urls: list[str] = []

    @asynccontextmanager
    async def __call__(self, url: str) -> AsyncIterator[FakeSocket]:
        self.urls.append(url)
        step = self.steps.pop(0) if self.steps else "hold"
        if isinstance(step, BaseException):
            raise step
        socket = HeldSocket(self.clock, step) if isinstance(step, float) else FakeSocket()
        self.sockets.append(socket)
        if step == "drop":
            await socket.incoming.put(None)
        yield socket


class HeldSocket(FakeSocket):
    """Stays open for `seconds` of fake time, then the server closes it."""

    def __init__(self, clock: "FakeClock", seconds: float) -> None:
        super().__init__()
        self.clock, self.seconds = clock, seconds

    async def _iter(self) -> AsyncIterator[str]:
        self.clock.now += self.seconds
        return
        yield ""


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


async def run_until(stream: FinnhubStream, sleeps: list[float], count: int) -> None:
    task = asyncio.create_task(stream.run())
    for _ in range(200):
        if len(sleeps) >= count:
            break
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(sleeps) >= count, sleeps


def make_stream(steps: list[object]) -> tuple[FinnhubStream, ScriptedConnector, list[float]]:
    clock = FakeClock()
    connector = ScriptedConnector(steps, clock)
    sleeps: list[float] = []

    async def record_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock.now += seconds
        await asyncio.sleep(0)

    stream = FinnhubStream(
        "secret-key",
        PriceHub(),
        connector=connector,
        sleep=record_sleep,
        clock=clock,
        jitter=lambda low, high: high,  # deterministic: always the top of the jitter range
    )
    return stream, connector, sleeps


def rejected(status: int, headers: dict[str, str] | None = None) -> InvalidStatus:
    return InvalidStatus(Response(status, "rejected", Headers(headers or {}), b""))


async def test_connections_dropped_right_after_the_handshake_keep_backing_off() -> None:
    # This is what Finnhub does to a second socket on the same key. Resetting the backoff on every
    # successful handshake used to make this a reconnect every second, forever.
    stream, _, sleeps = make_stream(["drop"] * 10)
    await run_until(stream, sleeps, 10)
    assert sleeps[:10] == [2, 4, 8, 16, 32, 64, 128, 256, 300, 300]


async def test_a_stable_connection_resets_the_backoff_and_resubscribes() -> None:
    stream, connector, sleeps = make_stream([OSError("refused"), OSError("refused"), 120.0, "drop"])
    await stream.acquire("AAPL")  # before connecting: queued, sent on connect
    await run_until(stream, sleeps, 4)
    # Two failures, then a connection that held for 2 minutes: the next retry starts from the bottom again.
    assert sleeps[:4] == [2, 4, 2, 2]
    assert all(s.sent == [{"type": "subscribe", "symbol": "AAPL"}] for s in connector.sockets)
    assert connector.urls[0].endswith("token=secret-key")


async def test_rate_limited_handshakes_wait_at_least_a_minute_or_retry_after() -> None:
    stream, _, sleeps = make_stream([rejected(429), rejected(429, {"Retry-After": "180"})])
    await run_until(stream, sleeps, 2)
    assert sleeps[:2] == [60, 180]


async def test_a_rejected_key_waits_long_and_says_so(caplog: pytest.LogCaptureFixture) -> None:
    stream, _, sleeps = make_stream([rejected(401)])
    with caplog.at_level(logging.WARNING, logger="app.ws.finnhub_stream"):
        await run_until(stream, sleeps, 1)
    assert sleeps[0] == 900
    assert "rejected the API key (HTTP 401)" in caplog.text


async def test_logs_name_the_close_code_and_contention_but_never_the_token(
    caplog: pytest.LogCaptureFixture,
) -> None:
    closed = ConnectionClosedError(Close(1008, "Too many connections"), None)
    stream, _, sleeps = make_stream([closed, "drop", rejected(429)])
    with caplog.at_level(logging.INFO, logger="app.ws.finnhub_stream"):
        await run_until(stream, sleeps, 3)
    assert "closed by server with code 1008: Too many connections (never connected)" in caplog.text
    assert "closed by server (was connected for 0s)" in caplog.text
    assert "handshake rejected with HTTP 429" in caplog.text
    assert "one WebSocket per API key" in caplog.text
    assert "secret-key" not in caplog.text


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

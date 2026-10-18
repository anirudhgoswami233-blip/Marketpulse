import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.ws.hub import CLIENT_QUEUE_SIZE, PriceHub, Trade

T0 = datetime(2026, 10, 19, 14, 0, tzinfo=UTC)


def trade(symbol: str, price: str, seconds: int = 0) -> Trade:
    return Trade(symbol=symbol, price=Decimal(price), timestamp=T0 + timedelta(seconds=seconds))


def drain(queue: asyncio.Queue[Trade]) -> list[Trade]:
    items = []
    while not queue.empty():
        items.append(queue.get_nowait())
    return items


def test_many_trades_between_flushes_send_one_update_per_symbol() -> None:
    hub = PriceHub()
    client = hub.register(frozenset({"AAPL", "MSFT"}))
    for i in range(50):
        hub.publish(trade("AAPL", f"{100 + i}", i))
    hub.publish(trade("TSLA", "200"))  # not subscribed

    assert hub.flush() == 1
    (update,) = drain(client.queue)
    assert update.price == Decimal("149")  # only the latest
    assert hub.flush() == 0  # nothing new


def test_out_of_order_trades_are_ignored() -> None:
    hub = PriceHub()
    hub.publish(trade("AAPL", "101", 10))
    hub.publish(trade("AAPL", "99", 5))
    last = hub.last_trade("AAPL")
    assert last is not None and last.price == Decimal("101")


def test_new_client_gets_last_known_price_immediately() -> None:
    hub = PriceHub()
    hub.publish(trade("AAPL", "101"))
    client = hub.register(frozenset({"AAPL"}))
    assert [t.price for t in drain(client.queue)] == [Decimal("101")]


def test_slow_client_drops_updates_instead_of_blocking() -> None:
    hub = PriceHub()
    slow = hub.register(frozenset({"AAPL"}))
    fast = hub.register(frozenset({"AAPL"}))
    for i in range(CLIENT_QUEUE_SIZE + 5):
        hub.publish(trade("AAPL", "100", i))
        hub.flush()
        drain(fast.queue)
    assert slow.queue.full()
    assert slow.dropped == 5


def test_unregistered_client_receives_nothing() -> None:
    hub = PriceHub()
    client = hub.register(frozenset({"AAPL"}))
    hub.unregister(client)
    hub.publish(trade("AAPL", "100"))
    hub.flush()
    assert client.queue.empty()

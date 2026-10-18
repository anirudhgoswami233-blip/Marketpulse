"""Server-Sent Events stream of live trades for the symbols a page is showing.

The browser never talks to Finnhub. Each SSE connection holds a reference on its symbols in the shared
Finnhub WebSocket, which is released when the browser disconnects.
"""

import asyncio
import json
import re
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.api.deps import ContainerDep
from app.container import Container
from app.models import Symbol
from app.services.search_service import STREAMABLE_EXCHANGES

router = APIRouter(prefix="/api/v1", tags=["stream"])

HEARTBEAT_S = 15.0
_SYMBOL = re.compile(r"^[A-Z0-9.\-^]{1,32}$")


@router.get("/stream")
async def stream(
    request: Request, container: ContainerDep, symbols: Annotated[str, Query(max_length=1024)]
) -> StreamingResponse:
    requested = list(dict.fromkeys(s.strip().upper() for s in symbols.split(",") if s.strip()))
    limit = container.settings.sse_max_symbols_per_client
    if not requested or len(requested) > limit:
        raise HTTPException(422, f"Provide between 1 and {limit} comma-separated symbols.")
    if any(not _SYMBOL.match(s) for s in requested):
        raise HTTPException(422, "Invalid symbol.")

    allowed = await _streamable(container, requested)
    return StreamingResponse(
        _events(request, container, requested, allowed),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _streamable(container: Container, symbols: list[str]) -> set[str]:
    async with container.session_factory() as session:
        rows = await session.execute(
            select(Symbol.symbol).where(
                Symbol.symbol.in_(symbols), Symbol.exchange_code.in_(STREAMABLE_EXCHANGES), Symbol.is_active
            )
        )
        return set(rows.scalars().all())


def _sse(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


async def _events(
    request: Request, container: Container, requested: list[str], allowed: set[str]
) -> AsyncIterator[str]:
    acquired: list[str] = []
    stream = container.stream
    if stream is not None:
        for symbol in requested:
            if symbol in allowed and await stream.acquire(symbol):
                acquired.append(symbol)
    client = container.hub.register(frozenset(acquired))
    try:
        yield _sse(
            "ready",
            {
                "live": acquired,
                "unavailable": [s for s in requested if s not in acquired],
                "streaming_enabled": stream is not None,
            },
        )
        while True:
            if await request.is_disconnected():
                break
            try:
                trade = await asyncio.wait_for(client.queue.get(), timeout=HEARTBEAT_S)
            except TimeoutError:
                yield ": keep-alive\n\n"
                continue
            yield _sse("price", trade.model_dump(mode="json"))
    finally:
        container.hub.unregister(client)
        if stream is not None:
            for symbol in acquired:
                await stream.release(symbol)

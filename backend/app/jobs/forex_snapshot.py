"""Refreshes the forex board's base pairs (Twelve Data) hourly while forex trades."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.container import Container
from app.services import forex_service

TASK_NAME = "forex-snapshot"


async def run(container: Container, *, background: bool = True) -> None:
    interval = timedelta(seconds=container.settings.forex_refresh_s)
    snapshot = await forex_service.load_snapshot(container.cache)
    if forex_service.needs_refresh(snapshot, datetime.now(UTC), interval):
        await forex_service.refresh(container.providers.forex_rates, container.cache, background=background)


def start_refresh(container: Container) -> None:
    """Start a refresh for a page that's waiting on it (interactive priority), unless one is running."""
    if not container.is_running(TASK_NAME):
        container.spawn(run(container, background=False), name=TASK_NAME)

from __future__ import annotations

from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.container import Container
from app.jobs import market_snapshot


def build_scheduler(container: Container) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=UTC)
    scheduler.add_job(
        market_snapshot.run,
        "interval",
        seconds=container.settings.overview_refresh_open_s,
        args=[container],
        id="market_snapshot",
        next_run_time=datetime.now(UTC),  # warm the overview at startup
        max_instances=1,
        coalesce=True,
    )
    return scheduler

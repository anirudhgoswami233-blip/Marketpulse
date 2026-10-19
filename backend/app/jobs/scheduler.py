from __future__ import annotations

from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.container import Container
from app.jobs import daily_brief, market_snapshot, signal_outcomes


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
    # Checks every 5 minutes for users whose local brief time has passed.
    scheduler.add_job(
        daily_brief.run,
        "interval",
        minutes=5,
        args=[container],
        id="daily_brief",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        signal_outcomes.run,
        "interval",
        hours=1,
        args=[container],
        id="signal_outcomes",
        next_run_time=datetime.now(UTC),
        max_instances=1,
        coalesce=True,
    )
    return scheduler

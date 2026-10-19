"""Runs the scheduled jobs one at a time each, whoever starts them.

The in-process scheduler runs them while the server is up; on hosts that sleep when idle (Render's free
tier) an external scheduler also calls `/api/v1/internal/jobs/run`. Both go through `run_exclusive`, so a
job never runs twice at once and its last result is visible to the caller.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from app.container import Container, JobState
from app.jobs import daily_brief, signal_outcomes

logger = logging.getLogger(__name__)

TRIGGERABLE_JOBS: dict[str, Callable[[Container], Awaitable[None]]] = {
    "daily_brief": daily_brief.run,
    "signal_outcomes": signal_outcomes.run,
}


def job_state(container: Container, name: str) -> JobState:
    return container.jobs.setdefault(name, JobState())


def is_job_running(container: Container, name: str) -> bool:
    return job_state(container, name).lock.locked() or container.is_running(f"job:{name}")


async def run_exclusive(container: Container, name: str) -> bool:
    """Run job `name` unless it's already running. Returns False when skipped. Failures are logged and
    recorded on the job's state, not raised: one failed run must not stop the next."""
    state = job_state(container, name)
    if state.lock.locked():
        logger.info("Job %s is already running; skipping this trigger", name)
        return False
    async with state.lock:
        state.last_started = datetime.now(UTC)
        state.last_error = None
        try:
            await TRIGGERABLE_JOBS[name](container)
        except Exception as exc:
            state.last_error = type(exc).__name__
            logger.exception("Job %s failed", name)
        finally:
            state.last_finished = datetime.now(UTC)
    return True

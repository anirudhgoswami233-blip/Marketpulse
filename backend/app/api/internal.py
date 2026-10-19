"""Endpoints for an external scheduler. Render's free tier sleeps when idle, which pauses the in-process
scheduler, so a GitHub Actions workflow wakes the server and starts the jobs here."""

import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Header, status

from app.api.deps import ContainerDep
from app.container import Container
from app.core.errors import AppError
from app.jobs.runner import TRIGGERABLE_JOBS, is_job_running, job_state, run_exclusive
from app.schemas.jobs import JobsStatusOut, JobStatusOut, JobsTriggeredOut

router = APIRouter(prefix="/api/v1/internal", tags=["internal"])


def require_cron_secret(
    container: ContainerDep, authorization: Annotated[str | None, Header()] = None
) -> None:
    expected = container.settings.cron_secret
    if expected is None or not expected.get_secret_value():
        # Not configured: behave as if the endpoint doesn't exist.
        raise AppError("Not found.", code="not_found", status=404)
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(
        token.encode(), expected.get_secret_value().encode()
    ):
        raise AppError("Invalid or missing credentials.", code="unauthorized", status=401)


CronAuth = Annotated[None, Depends(require_cron_secret)]


def _statuses(container: Container) -> list[JobStatusOut]:
    out = []
    for name in TRIGGERABLE_JOBS:
        state = job_state(container, name)
        out.append(
            JobStatusOut(
                name=name,
                running=is_job_running(container, name),
                last_started=state.last_started,
                last_finished=state.last_finished,
                last_error=state.last_error,
            )
        )
    return out


@router.get("/jobs", response_model=JobsStatusOut)
async def jobs_status(_: CronAuth, container: ContainerDep) -> JobsStatusOut:
    return JobsStatusOut(jobs=_statuses(container))


@router.post("/jobs/run", response_model=JobsTriggeredOut, status_code=status.HTTP_202_ACCEPTED)
async def run_jobs(_: CronAuth, container: ContainerDep) -> JobsTriggeredOut:
    """Start every job in the background and return at once. Poll `GET /jobs` for the outcome. Jobs run at
    background priority, so they can take minutes while the rate limiter spaces out their calls."""
    started, already_running = [], []
    for name in TRIGGERABLE_JOBS:
        if is_job_running(container, name):
            already_running.append(name)
            continue
        container.spawn(_run(container, name), name=f"job:{name}")
        started.append(name)
    return JobsTriggeredOut(jobs=_statuses(container), started=started, already_running=already_running)


async def _run(container: Container, name: str) -> None:
    await run_exclusive(container, name)

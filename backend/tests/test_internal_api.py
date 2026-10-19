import asyncio
import time
from collections.abc import Awaitable, Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.models  # noqa: F401
from app.container import Container
from app.jobs import runner
from app.main import create_app
from tests.api_helpers import file_db, make_settings

SECRET = "cron-secret-for-tests-0123456789"
AUTH = {"Authorization": f"Bearer {SECRET}"}


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace the real jobs with fakes that record their runs (and take a moment, like real ones)."""
    calls: list[str] = []

    def fake(name: str, fail: bool = False) -> Callable[[Container], Awaitable[None]]:
        async def job(container: Container) -> None:
            calls.append(name)
            await asyncio.sleep(0.2)
            if fail:
                raise RuntimeError("provider down")

        return job

    monkeypatch.setitem(runner.TRIGGERABLE_JOBS, "daily_brief", fake("daily_brief"))
    monkeypatch.setitem(runner.TRIGGERABLE_JOBS, "signal_outcomes", fake("signal_outcomes", fail=True))
    return calls


def _client(tmp_path: Path, **overrides: object) -> TestClient:
    return TestClient(create_app(make_settings(database_url=file_db(tmp_path), **overrides)))


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    with _client(tmp_path, cron_secret=SECRET) as test_client:
        yield test_client


def _wait_until_idle(client: TestClient) -> dict[str, dict[str, object]]:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        jobs = {j["name"]: j for j in client.get("/api/v1/internal/jobs", headers=AUTH).json()["jobs"]}
        if not any(j["running"] for j in jobs.values()):
            return jobs
        time.sleep(0.05)
    raise AssertionError("jobs did not finish")


def test_jobs_endpoints_are_hidden_without_a_configured_secret(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        assert client.post("/api/v1/internal/jobs/run", headers=AUTH).status_code == 404
        assert client.get("/api/v1/internal/jobs", headers=AUTH).status_code == 404


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer wrong"}, {"Authorization": SECRET}, {"Authorization": "Basic x"}],
)
def test_jobs_endpoints_reject_bad_credentials(
    client: TestClient, calls: list[str], headers: dict[str, str]
) -> None:
    assert client.post("/api/v1/internal/jobs/run", headers=headers).status_code == 401
    assert client.get("/api/v1/internal/jobs", headers=headers).status_code == 401
    assert calls == []


def test_trigger_runs_each_job_once_and_reports_the_outcome(client: TestClient, calls: list[str]) -> None:
    first = client.post("/api/v1/internal/jobs/run", headers=AUTH)
    assert first.status_code == 202
    assert first.json()["started"] == ["daily_brief", "signal_outcomes"]
    # A second trigger while they run doesn't start them again.
    second = client.post("/api/v1/internal/jobs/run", headers=AUTH).json()
    assert second["started"] == []
    assert second["already_running"] == ["daily_brief", "signal_outcomes"]

    jobs = _wait_until_idle(client)
    assert sorted(calls) == ["daily_brief", "signal_outcomes"]
    assert jobs["daily_brief"]["last_error"] is None
    assert jobs["daily_brief"]["last_finished"] is not None
    # Failures are reported by type only; details stay in the server log.
    assert jobs["signal_outcomes"]["last_error"] == "RuntimeError"


def test_scheduler_and_endpoint_share_one_lock(client: TestClient, calls: list[str]) -> None:
    container: Container = client.app.state.container  # type: ignore[attr-defined]
    assert client.portal is not None

    async def scheduler_run_then_trigger() -> tuple[bool, bool]:
        scheduled = asyncio.create_task(runner.run_exclusive(container, "daily_brief"))
        await asyncio.sleep(0.05)
        second = await runner.run_exclusive(container, "daily_brief")
        return await scheduled, second

    assert client.portal.call(scheduler_run_then_trigger) == (True, False)
    assert calls == ["daily_brief"]

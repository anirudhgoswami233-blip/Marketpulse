from datetime import datetime

from pydantic import BaseModel


class JobStatusOut(BaseModel):
    name: str
    running: bool
    last_started: datetime | None
    last_finished: datetime | None
    # Exception type of the last run's failure; details are in the server log.
    last_error: str | None


class JobsStatusOut(BaseModel):
    jobs: list[JobStatusOut]


class JobsTriggeredOut(JobsStatusOut):
    started: list[str]
    already_running: list[str]

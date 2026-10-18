"""Exchange trading-hours math from the regular schedule. Pure functions, no I/O.

This doesn't know about holidays; callers overlay the provider's market status where it's available (US).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.providers.base import MarketSession

# Forex trades 24 hours from Sunday 17:00 to Friday 17:00 New York time.
FOREX_TZ = ZoneInfo("America/New_York")
FOREX_ROLLOVER = time(17, 0)


@dataclass(frozen=True)
class ExchangeSchedule:
    code: str
    name: str
    timezone: str
    region: str
    sessions: tuple[tuple[time, time], ...]  # local times; empty means 24x5 (forex)


@dataclass(frozen=True)
class ScheduleStatus:
    is_open: bool
    session: MarketSession
    local_time: datetime
    next_change_at: datetime | None  # UTC time of the next open or close


def parse_schedule(row: dict[str, object]) -> ExchangeSchedule:
    raw_sessions = row.get("sessions") or []
    assert isinstance(raw_sessions, list)
    return ExchangeSchedule(
        code=str(row["code"]),
        name=str(row["name"]),
        timezone=str(row["timezone"]),
        region=str(row["region"]),
        sessions=tuple((time.fromisoformat(s[0]), time.fromisoformat(s[1])) for s in raw_sessions),
    )


def status_at(schedule: ExchangeSchedule, now: datetime) -> ScheduleStatus:
    if not schedule.sessions:
        return _forex_status(now)
    tz = ZoneInfo(schedule.timezone)
    local = now.astimezone(tz)
    for start, end in _sessions_on(schedule, local.date()):
        if start <= local < end:
            return ScheduleStatus(True, MarketSession.REGULAR, local, end.astimezone(UTC))
    return ScheduleStatus(False, MarketSession.CLOSED, local, _next_open(schedule, local))


def last_completed_session_date(schedule: ExchangeSchedule, now: datetime) -> date:
    """The most recent trading date whose regular session has fully closed (holidays not considered)."""
    local = now.astimezone(ZoneInfo(schedule.timezone))
    day = local.date()
    for _ in range(8):
        sessions = _sessions_on(schedule, day)
        if sessions and local >= sessions[-1][1]:
            return day
        day -= timedelta(days=1)
        local = datetime.combine(day, time(23, 59), tzinfo=local.tzinfo)
    return day


def _sessions_on(schedule: ExchangeSchedule, day: date) -> list[tuple[datetime, datetime]]:
    if day.weekday() >= 5:
        return []
    tz = ZoneInfo(schedule.timezone)
    return [
        (datetime.combine(day, s, tzinfo=tz), datetime.combine(day, e, tzinfo=tz))
        for s, e in schedule.sessions
    ]


def _next_open(schedule: ExchangeSchedule, local: datetime) -> datetime | None:
    day = local.date()
    for _ in range(8):
        for start, _end in _sessions_on(schedule, day):
            if start > local:
                return start.astimezone(UTC)
        day += timedelta(days=1)
    return None


def _forex_status(now: datetime) -> ScheduleStatus:
    ny = now.astimezone(FOREX_TZ)
    weekday, t = ny.weekday(), ny.time()
    closed = weekday == 5 or (weekday == 4 and t >= FOREX_ROLLOVER) or (weekday == 6 and t < FOREX_ROLLOVER)
    if closed:
        days_to_sunday = (6 - weekday) % 7
        reopen = datetime.combine(ny.date() + timedelta(days=days_to_sunday), FOREX_ROLLOVER, tzinfo=FOREX_TZ)
        return ScheduleStatus(False, MarketSession.CLOSED, now.astimezone(UTC), reopen.astimezone(UTC))
    days_to_friday = (4 - weekday) % 7
    close = datetime.combine(ny.date() + timedelta(days=days_to_friday), FOREX_ROLLOVER, tzinfo=FOREX_TZ)
    return ScheduleStatus(True, MarketSession.REGULAR, now.astimezone(UTC), close.astimezone(UTC))

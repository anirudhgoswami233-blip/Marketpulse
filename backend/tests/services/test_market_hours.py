from datetime import UTC, date, datetime

import pytest

from app.providers.base import MarketSession
from app.services.market_hours import ExchangeSchedule, last_completed_session_date, status_at
from app.services.reference_data import exchange_schedules


@pytest.fixture
def schedules() -> dict[str, ExchangeSchedule]:
    return exchange_schedules()


def utc(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def test_us_open_during_regular_hours(schedules: dict[str, ExchangeSchedule]) -> None:
    # Mon 2026-10-19 10:00 New York = 14:00 UTC (EDT)
    status = status_at(schedules["US"], utc(2026, 10, 19, 14, 0))
    assert status.is_open and status.session is MarketSession.REGULAR
    assert status.next_change_at == utc(2026, 10, 19, 20, 0)  # 16:00 EDT close
    assert status.local_time.hour == 10


def test_us_closed_on_weekend_reopens_monday(schedules: dict[str, ExchangeSchedule]) -> None:
    status = status_at(schedules["US"], utc(2026, 10, 18, 12, 0))  # Sunday
    assert not status.is_open
    assert status.next_change_at == utc(2026, 10, 19, 13, 30)


def test_tokyo_lunch_break_is_closed(schedules: dict[str, ExchangeSchedule]) -> None:
    # 12:00 Tokyo (UTC+9) = 03:00 UTC, inside the 11:30-12:30 break
    status = status_at(schedules["T"], utc(2026, 10, 19, 3, 0))
    assert not status.is_open
    assert status.next_change_at == utc(2026, 10, 19, 3, 30)


def test_india_open_in_ist(schedules: dict[str, ExchangeSchedule]) -> None:
    # 10:00 IST = 04:30 UTC
    assert status_at(schedules["NS"], utc(2026, 10, 19, 4, 30)).is_open
    assert not status_at(schedules["NS"], utc(2026, 10, 19, 10, 30)).is_open  # 16:00 IST


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (utc(2026, 10, 19, 14, 0), date(2026, 10, 16)),  # Monday mid-session -> Friday
        (utc(2026, 10, 19, 20, 30), date(2026, 10, 19)),  # Monday after close -> Monday
        (utc(2026, 10, 18, 12, 0), date(2026, 10, 16)),  # Sunday -> Friday
    ],
)
def test_last_completed_session(
    schedules: dict[str, ExchangeSchedule], now: datetime, expected: date
) -> None:
    assert last_completed_session_date(schedules["US"], now) == expected


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (utc(2026, 10, 21, 12, 0), date(2026, 10, 20)),  # Wednesday -> Tuesday
        (utc(2026, 10, 19, 12, 0), date(2026, 10, 16)),  # Monday -> Friday
        (utc(2026, 10, 18, 22, 0), date(2026, 10, 16)),  # Sunday evening (market reopened) -> Friday
    ],
)
def test_forex_last_completed_day(
    schedules: dict[str, ExchangeSchedule], now: datetime, expected: date
) -> None:
    assert last_completed_session_date(schedules["OANDA"], now) == expected


def test_forex_closed_on_saturday_and_open_midweek(schedules: dict[str, ExchangeSchedule]) -> None:
    saturday = status_at(schedules["OANDA"], utc(2026, 10, 17, 12, 0))
    assert not saturday.is_open
    assert saturday.next_change_at == utc(2026, 10, 18, 21, 0)  # Sunday 17:00 New York (EDT)
    assert status_at(schedules["OANDA"], utc(2026, 10, 21, 12, 0)).is_open

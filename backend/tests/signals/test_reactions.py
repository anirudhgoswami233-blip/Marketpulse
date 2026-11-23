from datetime import date
from decimal import Decimal

from app.signals.reactions import next_session_move


def _bars() -> list[tuple[date, Decimal]]:
    # Thu 100, Fri 110 (weekend gap), Mon 99
    return [
        (date(2026, 10, 15), Decimal("100")),
        (date(2026, 10, 16), Decimal("110")),
        (date(2026, 10, 19), Decimal("99")),
    ]


def test_next_session_move_after_a_headline() -> None:
    move = next_session_move(_bars(), date(2026, 10, 15))
    assert move is not None
    assert move.ref_date == date(2026, 10, 15)
    assert move.next_date == date(2026, 10, 16)
    assert move.move_pct == Decimal("10.00")


def test_reference_is_last_session_on_or_before_the_headline() -> None:
    # Headline on Saturday the 17th: reference is Friday, reaction is Monday.
    move = next_session_move(_bars(), date(2026, 10, 17))
    assert move is not None
    assert move.ref_date == date(2026, 10, 16)
    assert move.next_date == date(2026, 10, 19)
    assert move.move_pct == Decimal("-10.00")


def test_none_when_no_following_session_yet() -> None:
    assert next_session_move(_bars(), date(2026, 10, 19)) is None


def test_none_when_headline_predates_all_bars() -> None:
    assert next_session_move(_bars(), date(2026, 10, 1)) is None


def test_none_on_empty_bars_or_zero_reference() -> None:
    assert next_session_move([], date(2026, 10, 15)) is None
    bars = [(date(2026, 10, 15), Decimal("0")), (date(2026, 10, 16), Decimal("110"))]
    assert next_session_move(bars, date(2026, 10, 15)) is None

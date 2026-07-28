from datetime import time

import pytest

from backend.services.doctor_schedule import (
    ResolvedDoctorSchedule,
    SessionWindow,
    validate_recurring_schedule,
    validate_sessions,
)


def test_multiple_disjoint_sessions_are_canonicalized_and_sorted():
    assert validate_sessions([
        {"start": "17:00", "end": "21:00"},
        {"start": "09:00", "end": "12:00"},
    ]) == [
        {"start": "09:00", "end": "12:00"},
        {"start": "17:00", "end": "21:00"},
    ]


@pytest.mark.parametrize("sessions", [
    [{"start": "12:00", "end": "09:00"}],
    [{"start": "09:00", "end": "12:00"}, {"start": "11:59", "end": "14:00"}],
    [{"start": "09:00:30", "end": "12:00"}],
])
def test_invalid_or_overlapping_sessions_are_rejected(sessions):
    with pytest.raises(ValueError):
        validate_sessions(sessions)


def test_slot_grid_never_bridges_break_between_sessions():
    schedule = ResolvedDoctorSchedule(
        status="available",
        source="date_override",
        sessions=(
            SessionWindow(time(9), time(12)),
            SessionWindow(time(17), time(21)),
        ),
        token_limit=None,
    )
    slots = schedule.slots(30)
    assert time(11, 30) in slots
    assert time(12) not in slots
    assert time(16, 30) not in slots
    assert time(17) in slots
    assert time(20, 30) in slots


def test_recurring_schedule_rejects_non_weekday_keys():
    with pytest.raises(ValueError, match="0 through 6"):
        validate_recurring_schedule({"7": [{"start": "09:00", "end": "12:00"}]})

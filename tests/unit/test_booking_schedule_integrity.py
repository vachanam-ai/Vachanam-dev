from datetime import time

import pytest
from fastapi import HTTPException

from agent.tools.booking_tools import _generate_slots
from backend.models.schema import Doctor
from backend.routers.doctors import _validate_schedule


def _doctor(**overrides):
    values = {
        "name": "Dr. Schedule",
        "booking_type": "appointment",
        "working_hours_start": time(9, 0),
        "working_hours_end": time(17, 15),
        "available_weekdays": [0, 1, 2, 3, 4, 5],
        "slot_duration_minutes": 30,
        "max_concurrent_per_slot": 1,
        "status": "active",
    }
    values.update(overrides)
    return Doctor(**values)


def test_generated_slot_must_fit_entirely_inside_working_window():
    slots = _generate_slots(time(9, 0), time(17, 15), 30)
    assert time(16, 30) in slots
    assert time(17, 0) not in slots


@pytest.mark.parametrize(
    "overrides",
    [
        {"available_weekdays": []},
        {"working_hours_start": time(17, 0), "working_hours_end": time(9, 0)},
        {"working_hours_end": None},
        {
            "working_hours_start": time(9, 0),
            "working_hours_end": time(9, 15),
            "slot_duration_minutes": 30,
        },
    ],
)
def test_invalid_schedule_is_rejected_instead_of_looking_fully_booked(overrides):
    with pytest.raises(HTTPException) as exc:
        _validate_schedule(_doctor(**overrides))
    assert exc.value.status_code == 422


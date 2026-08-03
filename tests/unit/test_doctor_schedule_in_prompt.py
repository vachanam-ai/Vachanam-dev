"""The agent must quote a doctor's REAL sitting hours, split shifts included.

Real call 2026-08-03 (Vinay): Dr Srinivas sits 9-12 and again 5-9. The agent
said "available from 9 to 6" and left him out when listing who was available.

Root cause: d028e44 ("support exact-date multi-session doctors") deleted the
`sits {days} {hours}` line from the grounded prompt, because
working_hours_start/end is a single range and cannot express a split shift.
Nothing replaced it — the roster cache never serialized `recurring_schedule` —
so the model had no schedule ground truth at all. check_availability answers
only for a specific DATE, so a plain "what are his timings?" reached no tool
and the model invented an answer.
"""
from datetime import time

import pytest

from agent.prompts.grounded_prompt import _doctor_rows, _schedule_label
from agent.prompts.system_prompt import DoctorContext

WEEKDAYS = ["0", "1", "2", "3", "4"]


def _doctor(**overrides) -> DoctorContext:
    base = dict(
        id="d1",
        name="Srinivas",
        specialization="Dental",
        routing_keywords=["tooth"],
        booking_type="token",
        is_default=False,
    )
    base.update(overrides)
    return DoctorContext(**base)


def test_split_shift_shows_both_sittings_and_never_the_merged_span():
    """The bug verbatim: 9-12 + 5-9 must not collapse into one 9-to-6 range."""
    doc = _doctor(
        schedule={
            day: [{"start": "09:00", "end": "12:00"}, {"start": "17:00", "end": "21:00"}]
            for day in WEEKDAYS
        }
    )
    label = _schedule_label(doc)
    assert "9:00 AM-12:00 PM" in label
    assert "5:00 PM-9:00 PM" in label
    assert "9:00 AM-6:00 PM" not in label
    # The gap between sittings is the whole point — it must be visible.
    assert " and " in label


def test_days_sharing_hours_are_grouped_and_absent_days_are_omitted():
    doc = _doctor(
        schedule={
            "0": [{"start": "09:00", "end": "12:00"}],
            "1": [{"start": "09:00", "end": "12:00"}],
            "5": [{"start": "10:00", "end": "13:00"}],
        }
    )
    label = _schedule_label(doc)
    assert "Mon,Tue 9:00 AM-12:00 PM" in label
    assert "Sat 10:00 AM-1:00 PM" in label
    for absent in ("Wed", "Thu", "Fri", "Sun"):
        assert absent not in label


def test_date_specific_doctor_is_never_given_recurring_hours():
    """Missing date-specific data is UNKNOWN, never inferred as available."""
    doc = _doctor(schedule_mode="date_specific", schedule={})
    assert "check the exact date" in _schedule_label(doc)
    assert "AM" not in _schedule_label(doc)


def test_unconfigured_doctor_says_so_rather_than_inventing():
    assert _schedule_label(_doctor(schedule=None)) == "hours not set"


def test_prompt_rows_carry_the_hours_the_model_answers_from():
    rows = _doctor_rows([
        _doctor(schedule={"2": [{"start": "17:00", "end": "21:00"}]})
    ])
    assert "usual week: Wed 5:00 PM-9:00 PM" in rows
    # The old text told the model nothing was known — that was the regression.
    assert "schedule intentionally omitted" not in rows
    # The usual week is a routing aid only: a question about a NAMED day has to
    # hit the database, because leave and published sessions live there alone
    # (Vinay 2026-08-03: "always depend on DB for answering about doctors").
    assert "get_doctor_schedule" in rows


class _Row(dict):
    """asyncpg Record stand-in: JSONB columns arrive as raw TEXT."""


def test_serialize_doctors_carries_the_multi_session_schedule():
    from backend.services.clinic_cache import serialize_doctors

    class _Doc:
        id = "d1"
        name = "Srinivas"
        specialization = "Dental"
        routing_keywords = ["tooth"]
        booking_type = "token"
        is_default_doctor = False
        working_hours_start = time(9, 0)
        working_hours_end = time(18, 0)
        available_weekdays = [0, 1]
        schedule_mode = "recurring"
        recurring_schedule = {
            "0": [{"start": "09:00", "end": "12:00"}, {"start": "17:00", "end": "21:00"}]
        }

    payload = serialize_doctors([_Doc()])[0]
    assert payload["schedule"]["0"] == [
        {"start": "09:00", "end": "12:00"},
        {"start": "17:00", "end": "21:00"},
    ]
    # A configured recurring schedule WINS over the stale legacy 09:00-18:00
    # pair; that pair is exactly where a bogus "9 to 6" would come from.
    assert "1" not in payload["schedule"]


def test_serialize_doctors_falls_back_to_legacy_hours():
    from backend.services.clinic_cache import serialize_doctors

    class _Doc:
        id = "d2"
        name = "Priya"
        specialization = None
        routing_keywords = None
        booking_type = "appointment"
        is_default_doctor = True
        working_hours_start = time(10, 0)
        working_hours_end = time(13, 0)
        available_weekdays = [0, 4]
        schedule_mode = "recurring"
        recurring_schedule = {}

    payload = serialize_doctors([_Doc()])[0]
    assert payload["schedule"] == {
        "0": [{"start": "10:00", "end": "13:00"}],
        "4": [{"start": "10:00", "end": "13:00"}],
    }


@pytest.mark.parametrize(
    "raw,fallback,expected",
    [
        ('[0, 1, 2]', [], [0, 1, 2]),
        ('{"0": []}', {}, {"0": []}),
        (None, [], []),
        ("not json", [], []),
        ([3], [], [3]),
    ],
)
def test_jsonb_text_is_decoded_not_iterated(raw, fallback, expected):
    """list("[0,1,2]") yields characters. No codec is registered on the prewarm
    connection, so JSONB must be parsed, never coerced."""
    from agent.livekit_minimal.agent import _decode_jsonb

    assert _decode_jsonb(raw, fallback) == expected

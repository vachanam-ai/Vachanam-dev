"""A doctor's real week reaches the clinic calendar.

Vinay 2026-08-04: "fix calender. it should update doctors and appointments.
rightnw appointments getting updated in realtime. but, doctors and their slots
appear static from creation of clinic."

`upsert_doctor_hours_event` models a doctor as ONE repeating block — one start,
one end, one RRULE. A doctor sitting 9-12 and again 5-9 cannot be said that
way, so the router classed them "complex", DELETED their hours block and
returned. Every split-session doctor (which is all of Vinay's) therefore had no
current hours at all, and whatever the calendar still showed was the simple
block written when the clinic was created.

A week is now a set of WINDOWS: (start, end, weekdays).
"""
from datetime import time

import pytest

from backend.services.doctor_calendar import (
    doctor_windows,
    windows_from_legacy,
    windows_from_recurring,
)


def _sessions(*pairs):
    return [{"start": s, "end": e} for s, e in pairs]


# ── the case that was silently dropped ───────────────────────────────────────

def test_split_sessions_become_two_windows():
    """Srinivas: 9-12 and again 5-9. Previously deleted from the calendar."""
    out = windows_from_recurring({
        str(d): _sessions(("09:00", "12:00"), ("17:00", "21:00")) for d in range(6)
    })
    assert out == [
        (time(9, 0), time(12, 0), [0, 1, 2, 3, 4, 5]),
        (time(17, 0), time(21, 0), [0, 1, 2, 3, 4, 5]),
    ]


def test_days_sharing_a_window_collapse_into_one_event():
    """Five identical weekdays must be ONE recurring event with BYDAY, not
    five — Google counts events, and a month of split sessions across six
    doctors would otherwise be hundreds of rows."""
    out = windows_from_recurring({str(d): _sessions(("09:00", "12:00")) for d in range(5)})
    assert out == [(time(9, 0), time(12, 0), [0, 1, 2, 3, 4])]


def test_different_hours_on_different_days_stay_separate():
    out = windows_from_recurring({
        "0": _sessions(("09:00", "12:00")),
        "1": _sessions(("10:00", "13:00")),
    })
    assert out == [
        (time(9, 0), time(12, 0), [0]),
        (time(10, 0), time(13, 0), [1]),
    ]


# ── nothing garbage reaches Google ───────────────────────────────────────────

@pytest.mark.parametrize("bad", [
    {"0": [{"start": "09:00", "end": "09:00"}]},   # zero length
    {"0": [{"start": "18:00", "end": "09:00"}]},   # end before start
    {"0": [{"start": "", "end": "12:00"}]},        # unparseable
    {"0": [{"start": None, "end": None}]},
    {"9": [{"start": "09:00", "end": "12:00"}]},   # not a weekday
    {"x": [{"start": "09:00", "end": "12:00"}]},   # not a number
])
def test_unusable_sessions_are_skipped(bad):
    assert windows_from_recurring(bad) == []


def test_an_empty_schedule_yields_nothing():
    assert windows_from_recurring({}) == []
    assert windows_from_recurring(None) == []


# ── the legacy shape still works ─────────────────────────────────────────────

def test_a_doctor_never_re_published_keeps_their_old_hours():
    """Doctors predating the schedule editor still have working_hours_* only;
    dropping them would erase their hours from the calendar."""
    out = windows_from_legacy(time(9, 0), time(18, 0), [0, 1, 2])
    assert out == [(time(9, 0), time(18, 0), [0, 1, 2])]


def test_legacy_with_no_weekdays_defaults_to_the_whole_week():
    out = windows_from_legacy(time(9, 0), time(18, 0), None)
    assert out == [(time(9, 0), time(18, 0), [0, 1, 2, 3, 4, 5, 6])]


@pytest.mark.parametrize("start,end", [(None, time(18, 0)), (time(9, 0), None),
                                       (time(18, 0), time(9, 0))])
def test_legacy_without_usable_hours_yields_nothing(start, end):
    assert windows_from_legacy(start, end, [0]) == []


# ── which source wins ────────────────────────────────────────────────────────

class _Doc:
    def __init__(self, recurring=None, start=None, end=None, weekdays=None):
        self.recurring_schedule = recurring
        self.working_hours_start = start
        self.working_hours_end = end
        self.available_weekdays = weekdays


def test_the_published_schedule_beats_the_legacy_hours():
    """Once a doctor publishes a real week, the old single window is stale."""
    doc = _Doc(
        recurring={"0": _sessions(("10:00", "13:00"))},
        start=time(9, 0), end=time(18, 0), weekdays=[0, 1, 2],
    )
    assert doctor_windows(doc) == [(time(10, 0), time(13, 0), [0])]


def test_legacy_is_used_when_nothing_has_been_published():
    doc = _Doc(recurring={}, start=time(9, 0), end=time(18, 0), weekdays=[0])
    assert doctor_windows(doc) == [(time(9, 0), time(18, 0), [0])]


def test_a_doctor_with_no_hours_at_all_publishes_nothing():
    assert doctor_windows(_Doc()) == []


# ── the router no longer throws split schedules away ─────────────────────────

def test_the_router_publishes_windows_instead_of_deleting_them():
    import inspect

    from backend.routers import doctors

    src = inspect.getsource(doctors._maybe_upsert_recurring_cal_event)
    assert "doctor_windows" in src
    assert "sync_doctor_session_events" in src


def test_publishing_a_date_schedule_syncs_the_calendar():
    """The other half: PUT /schedule/{date} wrote the DB and never told Google,
    so a doctor publishing next week changed nothing the clinic could see."""
    import inspect

    from backend.routers import availability

    src = inspect.getsource(availability.publish_date_schedule)
    assert "sync_date_schedule_events" in src

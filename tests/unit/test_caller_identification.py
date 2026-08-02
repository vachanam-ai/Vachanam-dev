"""Caller identification at inbound call start (Vinay 2026-06-14).

_build_caller_context detects whether a phone-scoped lookup has upcoming rows,
but never places patient names or appointment details in the greeting/prompt.
The caller must explicitly ask before find_my_bookings fetches those records.

These are pure-function tests over stub rows (no DB) — they prove the new-vs-
existing branching and the family-shared-number guard (don't reveal one name).
"""
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace as NS

from agent.livekit_minimal.agent import _build_caller_context

TODAY = date(2026, 6, 14)


def _row(*, status="confirmed", days=1, name="Vinay", doctor="Dr. Skin",
         booking_type="appointment", appt=time(11, 0), token_number=3, tid="tok-1"):
    t = NS(
        id=tid, status=status, date=TODAY + timedelta(days=days),
        appointment_time=appt, token_number=token_number,
    )
    d = NS(name=doctor, booking_type=booking_type)
    p = NS(name=name)
    return (t, d, p)


def test_new_caller_returns_no_name_no_extra():
    # No confirmed future bookings → treated as a new caller.
    name, extra = _build_caller_context([], TODAY)
    assert name is None
    assert extra == ""


def test_only_clinic_cancelled_is_not_an_existing_future_booking():
    rows = [_row(status="cancelled_by_clinic")]
    name, extra = _build_caller_context(rows, TODAY)
    assert name is None
    assert extra == ""


def test_single_future_booking_is_private_until_explicit_request():
    rows = [_row(name="Vinay", doctor="Dr. Skin", tid="tok-abc")]
    name, extra = _build_caller_context(rows, TODAY)
    assert name is None
    assert "find_my_bookings" in extra
    assert "explicitly asks" in extra
    assert "tok-abc" not in extra
    assert "Vinay" not in extra
    assert "Dr. Skin" not in extra


def test_past_booking_is_ignored():
    rows = [_row(days=-2)]  # yesterday-ish → not a future booking
    name, extra = _build_caller_context(rows, TODAY)
    assert name is None
    assert extra == ""


def test_past_same_day_clock_booking_is_not_greeted_as_upcoming():
    rows = [_row(days=0, appt=time(16, 0))]
    name, extra = _build_caller_context(rows, datetime(2026, 6, 14, 19, 0))
    assert name is None
    assert extra == ""


def test_later_same_day_clock_booking_remains_upcoming():
    rows = [_row(days=0, appt=time(20, 0))]
    name, extra = _build_caller_context(rows, datetime(2026, 6, 14, 19, 0))
    assert name is None
    assert "find_my_bookings" in extra
    assert "8:00 PM" not in extra


def test_family_shared_number_does_not_reveal_a_single_name():
    rows = [
        _row(name="Amma", tid="t1"),
        _row(name="Abbayi", tid="t2"),
    ]
    name, extra = _build_caller_context(rows, TODAY)
    assert name is None
    assert "verified inbound number" in extra
    assert "Amma" not in extra and "Abbayi" not in extra
    assert "t1" not in extra and "t2" not in extra

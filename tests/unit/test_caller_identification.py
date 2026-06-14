"""Caller identification at inbound call start (Vinay 2026-06-14).

_build_caller_context maps a returning caller's existing bookings to:
  - a greeting name (welcome them by name), and
  - a system-prompt block that hands the agent their FUTURE bookings so it can
    handle "wants a new booking but already has one" without a tool round-trip.

These are pure-function tests over stub rows (no DB) — they prove the new-vs-
existing branching and the family-shared-number guard (don't reveal one name).
"""
from datetime import date, time, timedelta
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


def test_single_future_booking_greets_by_name_and_lists_it():
    rows = [_row(name="Vinay", doctor="Dr. Skin", tid="tok-abc")]
    name, extra = _build_caller_context(rows, TODAY)
    assert name == "Vinay"
    assert "EXISTING patient" in extra
    assert "token_id=tok-abc" in extra
    assert "Dr. Skin" in extra
    # The new-vs-existing instruction must be present.
    assert "reschedule" in extra.lower()
    assert "separate new booking" in extra.lower()


def test_past_booking_is_ignored():
    rows = [_row(days=-2)]  # yesterday-ish → not a future booking
    name, extra = _build_caller_context(rows, TODAY)
    assert name is None
    assert extra == ""


def test_family_shared_number_does_not_reveal_a_single_name():
    rows = [
        _row(name="Amma", tid="t1"),
        _row(name="Abbayi", tid="t2"),
    ]
    name, extra = _build_caller_context(rows, TODAY)
    assert name is None  # ambiguous — never greet by one family member's name
    assert "several patients share this number" in extra
    assert "token_id=t1" in extra and "token_id=t2" in extra

"""A missed appointment is still reschedulable for the rest of that day.

Vinay, 2026-08-03:

    reschedule not working. today i had appointment at 8:45. i called at 11
    saying i couldn't make it, can you reschedule. now it is saying i don't
    have any appointments at all at that time.

ROOT CAUSE: `find_bookings_by_phone` filtered its rows through
`booking_is_upcoming`, which returns False for a TODAY appointment whose clock
time has passed. The 8:45 row was dropped from the lookup at 11:00, so the
agent truthfully reported no bookings — while the row sat in the table.

The status lifecycle is the proof it was wrong: confirmed -> attended |
no_show. A token still at `confirmed` after its time means the receptionist
never marked anyone seen. That is precisely the patient who missed their slot
and is ringing to move it — the call Vachanam exists to catch.

`booking_is_upcoming` keeps its narrow meaning (used for greeting and for
duplicate-booking checks, where calling a passed slot "upcoming" would be a
lie); `booking_is_actionable` is the wider one used for find/move/cancel.
"""
from datetime import date, datetime, time, timedelta

import pytest

from agent.tools.booking_tools import booking_is_actionable, booking_is_upcoming


class _T:
    def __init__(self, *, status="confirmed", d=None, t=None):
        self.status = status
        self.date = d or date(2026, 8, 3)
        self.appointment_time = t


NOW = datetime(2026, 8, 3, 11, 0)  # 11:00 on the day of the appointment


# ── the reported bug ─────────────────────────────────────────────────────────

def test_this_mornings_missed_slot_is_still_actionable():
    """8:45 booking, caller rings at 11:00 — must be findable and movable."""
    tok = _T(t=time(8, 45))
    assert booking_is_actionable(tok, NOW) is True


def test_and_it_is_still_correctly_not_called_upcoming():
    """The narrow predicate must NOT change — the agent still must never
    describe a passed appointment as one that is coming up."""
    assert booking_is_upcoming(_T(t=time(8, 45)), NOW) is False


# ── the boundaries that keep it honest ───────────────────────────────────────

def test_yesterdays_booking_is_not_actionable():
    tok = _T(d=NOW.date() - timedelta(days=1), t=time(8, 45))
    assert booking_is_actionable(tok, NOW) is False


def test_a_later_slot_today_is_actionable():
    assert booking_is_actionable(_T(t=time(17, 30)), NOW) is True


def test_tomorrows_booking_is_actionable():
    tok = _T(d=NOW.date() + timedelta(days=1), t=time(8, 45))
    assert booking_is_actionable(tok, NOW) is True


def test_a_todays_token_queue_booking_has_no_time_and_stays_actionable():
    assert booking_is_actionable(_T(t=None), NOW) is True


@pytest.mark.parametrize("status", ["attended", "no_show", "cancelled_by_patient",
                                    "cancelled_by_clinic"])
def test_a_closed_out_booking_is_never_actionable(status):
    """Once the clinic has marked the outcome, or either side cancelled, there
    is nothing left to move."""
    assert booking_is_actionable(_T(status=status, t=time(8, 45)), NOW) is False


# ── the call sites that were wrong ───────────────────────────────────────────

def test_the_caller_lookup_uses_the_wider_predicate():
    import inspect

    from agent.tools import booking_tools

    src = inspect.getsource(booking_tools.find_bookings_by_phone)
    assert "booking_is_actionable" in src
    assert "booking_is_upcoming" not in src, (
        "the caller lookup must not drop this morning's missed appointment"
    )


@pytest.mark.parametrize("tool", ["_do_reschedule", "_do_cancel"])
def test_the_mutation_tools_use_the_wider_predicate(tool):
    import inspect

    from agent.livekit_minimal.agent import VachanamAgent

    src = inspect.getsource(getattr(VachanamAgent, tool))
    assert "booking_is_actionable" in src


def test_the_greeting_path_still_uses_the_narrow_one():
    """RULE: never greet a caller about an appointment that already happened."""
    import inspect

    from agent.livekit_minimal import agent as agent_mod

    src = inspect.getsource(agent_mod)
    assert "booking_is_upcoming(t, now_local)" in src

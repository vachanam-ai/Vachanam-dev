"""No reminder call for a booking made within the hour.

Vinay 2026-08-07: "if appointment is booked at 5:40 for 6pm. then remainder
call not needed. say it for 1hr. like if i book at 5 for 6 then appointment
call not needed."

The 30-minute reminder assumed every appointment was arranged well in advance.
A booking made at 17:40 for 18:00 got a reminder call at ~17:30 — twenty
minutes after the patient hung up from arranging it. Eligibility is now
measured from when the booking was MADE, the same way the day-before call
already measures it (booked_far_enough_ahead).

Inclusive at exactly one hour, which is the case he named: booked at 5 for 6
gets no call.
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from backend.jobs.pre_appt_reminder import (
    MIN_LEAD_MINUTES,
    booked_far_enough_ahead,
    booked_too_close,
)

IST = ZoneInfo("Asia/Kolkata")
APPT_DATE = datetime(2026, 8, 7, tzinfo=IST).date()
SIX_PM = datetime(2026, 8, 7, 18, 0, tzinfo=IST).timetz()


def _made_at(hh, mm):
    """Booking creation time, stored UTC as the DB does."""
    return datetime(2026, 8, 7, hh, mm, tzinfo=IST).astimezone(timezone.utc)


@pytest.mark.parametrize("hh,mm", [(17, 40), (17, 5), (17, 59), (18, 0)])
def test_booked_inside_the_hour_gets_no_reminder(hh, mm):
    assert booked_too_close(_made_at(hh, mm), APPT_DATE, SIX_PM, IST) is True


def test_exactly_one_hour_is_still_too_close():
    """The literal case: "if i book at 5 for 6 then appointment call not
    needed" — so the boundary is inclusive."""
    assert booked_too_close(_made_at(17, 0), APPT_DATE, SIX_PM, IST) is True


def test_a_minute_earlier_still_gets_its_reminder():
    assert booked_too_close(_made_at(16, 59), APPT_DATE, SIX_PM, IST) is False


@pytest.mark.parametrize("hh,mm", [(9, 0), (12, 30), (16, 0)])
def test_bookings_made_well_ahead_are_unaffected(hh, mm):
    assert booked_too_close(_made_at(hh, mm), APPT_DATE, SIX_PM, IST) is False


def test_a_naive_created_at_is_read_as_utc_not_local():
    """created_at comes back naive from some drivers. Read as local it would
    be 5.5h off and silently suppress or allow the wrong reminders."""
    naive = datetime(2026, 8, 7, 12, 30)  # 18:00 IST -> too close
    assert booked_too_close(naive, APPT_DATE, SIX_PM, IST) is True
    naive_early = datetime(2026, 8, 7, 6, 0)  # 11:30 IST -> plenty of lead
    assert booked_too_close(naive_early, APPT_DATE, SIX_PM, IST) is False


def test_unknown_booking_time_still_gets_its_reminder():
    """Fail toward calling. A missed reminder is worse than an extra one."""
    assert booked_too_close(None, APPT_DATE, SIX_PM, IST) is False
    assert booked_too_close(_made_at(17, 40), APPT_DATE, None, IST) is False


def test_the_two_lead_rules_do_not_contradict_each_other():
    """The day-before call needs >=24h of lead; this one needs >1h. A booking
    can legitimately fail both (same-day, well ahead) — it then gets only the
    30-minute call, which is the documented behaviour."""
    same_day_early = _made_at(9, 0)
    assert booked_far_enough_ahead(same_day_early, APPT_DATE, SIX_PM, IST) is False
    assert booked_too_close(same_day_early, APPT_DATE, SIX_PM, IST) is False


def test_the_window_is_one_hour():
    assert MIN_LEAD_MINUTES == 60


def test_the_job_skips_and_marks_so_it_is_not_rescanned():
    """Marking reminder_sent matters: without it the row is re-read from
    Postgres every single minute until the appointment passes."""
    import inspect

    from backend.jobs import pre_appt_reminder

    src = inspect.getsource(pre_appt_reminder.run_pre_appt_reminders)
    assert "booked_too_close" in src
    block = src.split("booked_too_close")[1].split("continue")[0]
    assert "reminder_sent = True" in block

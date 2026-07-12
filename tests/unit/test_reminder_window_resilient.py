"""Regression: the pre-appointment reminder window must be RESILIENT (FIXLOG).

The old 28-31 min band was 3 min wide; a single missed scheduler tick (Render
free-tier restart/gap) dropped the reminder permanently. The window now spans
[now, now+31min] so a missed 30-min mark still catches up at a later tick, while
past appointments stay excluded.
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from backend.jobs.pre_appt_reminder import reminder_window, appointment_in_window

IST = ZoneInfo("Asia/Kolkata")


def _appt_in(now: datetime, minutes_ahead: float) -> bool:
    lo, hi = reminder_window(now)
    appt_dt = now + timedelta(minutes=minutes_ahead)
    return appointment_in_window(appt_dt.date(), appt_dt.timetz().replace(tzinfo=None), lo, hi)


def test_fires_at_30_min_before():
    now = datetime(2026, 6, 22, 16, 0, tzinfo=IST)
    assert _appt_in(now, 30) is True


def test_catches_up_after_missed_tick_5_min_before():
    # The 30/28-min marks were missed (Render gap); at 5 min before it must STILL fire.
    now = datetime(2026, 6, 22, 16, 25, tzinfo=IST)
    assert _appt_in(now, 5) is True


def test_fires_right_up_to_appointment_time():
    now = datetime(2026, 6, 22, 16, 29, tzinfo=IST)
    assert _appt_in(now, 1) is True


def test_does_not_fire_too_early_beyond_window():
    now = datetime(2026, 6, 22, 16, 0, tzinfo=IST)
    assert _appt_in(now, 45) is False  # 45 min out → wait until inside 31 min


def test_does_not_fire_for_past_appointment():
    now = datetime(2026, 6, 22, 16, 35, tzinfo=IST)
    assert _appt_in(now, -5) is False  # appointment already passed


def test_window_does_not_wrap_near_midnight():
    now = datetime(2026, 6, 22, 23, 50, tzinfo=IST)
    lo, hi = reminder_window(now)
    assert lo <= hi  # datetimes, never a wrapped (lo>hi) time-only compare
    assert _appt_in(now, 20) is True  # appt 00:10 next day still fires


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))

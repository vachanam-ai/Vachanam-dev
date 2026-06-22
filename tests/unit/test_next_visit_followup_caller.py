from datetime import datetime, date
from zoneinfo import ZoneInfo
from types import SimpleNamespace
from backend.jobs.next_visit_followup_caller import _is_due

IST = ZoneInfo("Asia/Kolkata")


def _task(tt, sched):
    return SimpleNamespace(task_type=tt, scheduled_date=sched, attempt_count=0, status="pending")


def test_next_visit_book_due_after_9am():
    assert _is_due(_task("next_visit_book", date(2026, 6, 23)), datetime(2026, 6, 23, 9, 5, tzinfo=IST)) is True

def test_next_visit_book_not_due_before_9am():
    assert _is_due(_task("next_visit_book", date(2026, 6, 23)), datetime(2026, 6, 23, 8, 0, tzinfo=IST)) is False

def test_doctor_advice_due_within_hours():
    assert _is_due(_task("doctor_advice", date(2026, 6, 23)), datetime(2026, 6, 23, 14, 0, tzinfo=IST)) is True

def test_nothing_due_at_night():
    now = datetime(2026, 6, 23, 22, 0, tzinfo=IST)
    assert _is_due(_task("doctor_advice", date(2026, 6, 23)), now) is False
    assert _is_due(_task("next_visit_book", date(2026, 6, 23)), now) is False

def test_future_scheduled_not_due():
    assert _is_due(_task("next_visit_book", date(2026, 6, 25)), datetime(2026, 6, 23, 10, 0, tzinfo=IST)) is False

"""Unit tests for backend/jobs/calendar_writer.py.

Tests:
  1. test_backoff_schedule            — verifies BACKOFF_SECONDS constant + _compute_next_attempt math.
  2. test_permanent_fail_after_5_attempts — task with attempts=4 + simulated failure
                                            → status='failed_permanent' + admin_alert called once.
  3. test_success_marks_done_and_writes_event_id — 'create' op + mocked Cal call
                                                   → status='done' + google_event_id + Token updated.
  4. test_retry_increments_attempts_and_schedules_next — attempts=1 + simulated failure
                                                          → attempts=2 + next_attempt_at ≈ now + 30s.

Tests 2-4 use the `db` conftest fixture (test Postgres).  They are tagged
pytest.mark.requires_db so the CI unit-test job can gate them separately.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone, date, time
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from backend.jobs.calendar_writer import (
    BACKOFF_SECONDS,
    _compute_next_attempt,
    _process_one_task,
)
from backend.models.schema import (
    Branch,
    CalendarWriteTask,
    Doctor,
    Organization,
    Patient,
    Token,
)

UTC = timezone.utc


# ---------------------------------------------------------------------------
# 1. Pure-unit test — no DB required
# ---------------------------------------------------------------------------


def test_backoff_schedule() -> None:
    """BACKOFF_SECONDS must be [5, 30, 300, 3600] and _compute_next_attempt
    must return base + the correct delta for each attempt index."""
    assert BACKOFF_SECONDS == [5, 30, 300, 3600]

    base = datetime(2026, 6, 9, 10, 0, 0, tzinfo=timezone.utc)
    assert _compute_next_attempt(1, base) == base + timedelta(seconds=5)
    assert _compute_next_attempt(2, base) == base + timedelta(seconds=30)
    assert _compute_next_attempt(3, base) == base + timedelta(seconds=300)
    assert _compute_next_attempt(4, base) == base + timedelta(seconds=3600)


# ---------------------------------------------------------------------------
# Helpers — build the minimum ORM graph needed to create a CalendarWriteTask
# without violating FK constraints in the test DB.
# ---------------------------------------------------------------------------


async def _make_write_task(db, *, attempts: int, operation: str = "create") -> CalendarWriteTask:
    """Insert a minimal CalendarWriteTask (with all FK parents) and return it."""
    org = Organization(
        name="Test Org",
        owner_phone="9999999999",
        owner_email=f"org_{uuid.uuid4().hex[:8]}@test.com",
        plan="clinic",
    )
    db.add(org)
    await db.flush()

    branch = Branch(
        org_id=org.id,
        name="Test Branch",
        whatsapp_number=f"+91{uuid.uuid4().int % 10_000_000_000:010d}",
    )
    db.add(branch)
    await db.flush()

    doctor = Doctor(
        branch_id=branch.id,
        name="Dr Test",
        booking_type="appointment",
    )
    db.add(doctor)
    await db.flush()

    patient = Patient(
        branch_id=branch.id,
        name="Patient Test",
        phone="+919876543210",
    )
    db.add(patient)
    await db.flush()

    token = Token(
        branch_id=branch.id,
        doctor_id=doctor.id,
        patient_id=patient.id,
        date=date(2026, 6, 20),
        source="walk_in",
        appointment_time=time(10, 0),
    )
    db.add(token)
    await db.flush()

    task = CalendarWriteTask(
        branch_id=branch.id,
        token_id=token.id,
        operation=operation,
        payload_json={
            "calendar_id": "cal_test",
            "patient_first_name": "Patient",
            "patient_phone_last4": "3210",
            "appointment_dt": "2026-06-20T10:00:00",
            "duration_minutes": 30,
            "doctor_name": "Dr Test",
        },
        attempts=attempts,
        status="pending",
    )
    db.add(task)
    await db.commit()
    return task


# ---------------------------------------------------------------------------
# 2. Permanent fail after 5 attempts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_permanent_fail_after_5_attempts(db) -> None:
    """A task with attempts=4 that fails once more must become 'failed_permanent'.
    admin_alert must be called exactly once."""
    task = await _make_write_task(db, attempts=4)

    with (
        patch(
            "backend.jobs.calendar_writer._do_calendar_op",
            side_effect=Exception("simulated failure"),
        ),
        patch(
            "backend.jobs.calendar_writer.alert_admin",
            new_callable=AsyncMock,
        ) as mock_alert,
    ):
        await _process_one_task(db, task)

    await db.refresh(task)
    assert task.status == "failed_permanent", f"expected failed_permanent, got {task.status}"
    assert task.attempts == 5
    assert "simulated failure" in (task.last_error or "")
    mock_alert.assert_awaited_once()
    call_args = mock_alert.call_args
    assert call_args.args[0] == "calendar_write_failed_permanent"


# ---------------------------------------------------------------------------
# 3. Success marks done + writes google_event_id to task AND Token
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_success_marks_done_and_writes_event_id(db) -> None:
    """A 'create' task that succeeds must become 'done', populate
    google_event_id on the task, and write google_calendar_event_id on Token."""
    task = await _make_write_task(db, attempts=0, operation="create")
    token_id = task.token_id

    fake_event_id = "evt_test_abc123"

    with patch(
        "backend.jobs.calendar_writer._do_calendar_op",
        new_callable=AsyncMock,
        return_value=fake_event_id,
    ):
        await _process_one_task(db, task)

    await db.refresh(task)
    assert task.status == "done", f"expected done, got {task.status}"
    assert task.google_event_id == fake_event_id

    token: Token | None = await db.get(Token, token_id)
    assert token is not None
    assert token.google_calendar_event_id == fake_event_id


# ---------------------------------------------------------------------------
# 4. Failure at attempts=1 → retry scheduled at now + 30s
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retry_increments_attempts_and_schedules_next(db) -> None:
    """A task with attempts=1 that fails must increment to attempts=2
    and schedule next_attempt_at ≈ now + 30s (BACKOFF_SECONDS[1])."""
    task = await _make_write_task(db, attempts=1)

    before = datetime.now(timezone.utc)

    with patch(
        "backend.jobs.calendar_writer._do_calendar_op",
        side_effect=Exception("transient error"),
    ):
        await _process_one_task(db, task)

    after = datetime.now(timezone.utc)

    await db.refresh(task)
    assert task.status == "pending", f"expected pending, got {task.status}"
    assert task.attempts == 2

    expected_delta = timedelta(seconds=30)
    # next_attempt_at should be between (before + 30s) and (after + 30s) with 2s tolerance
    lower = before + expected_delta - timedelta(seconds=2)
    upper = after + expected_delta + timedelta(seconds=2)

    # Normalise: make next_at timezone-aware UTC for comparison
    next_at = task.next_attempt_at
    if next_at is not None and (next_at.tzinfo is None):
        next_at = next_at.replace(tzinfo=timezone.utc)

    assert lower <= next_at <= upper, (
        f"next_attempt_at={next_at} outside expected window [{lower}, {upper}]"
    )

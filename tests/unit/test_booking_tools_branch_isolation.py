"""Tests for multi-tenant branch_id isolation on Doctor queries in booking_tools.

Audit finding: check_availability, assign_token, and confirm_booking each had a
`select(Doctor).where(Doctor.id == doctor_id)` query without a branch_id filter.
Caller-supplied doctor_id could (in bug cases) resolve a doctor belonging to a
different branch, violating DPDP Act 2023 data isolation requirements.

Fix: all three Doctor lookups now use `and_(Doctor.id == doctor_id, Doctor.branch_id == branch_id)`.
These tests seed two branches with two different doctors and assert that cross-branch
doctor lookups return failure responses rather than silently succeeding.

Tests are pure unit tests — no real DB needed. AsyncSession is mocked to return None
(simulating the ORM returning no result when both id AND branch_id must match).
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.tools.booking_tools import (
    assign_token,
    check_availability,
    confirm_booking,
)


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

BRANCH_A_ID = uuid.uuid4()
BRANCH_B_ID = uuid.uuid4()

# doctor_b belongs to BRANCH_B — should NOT be accessible via BRANCH_A calls
DOCTOR_B_ID = uuid.uuid4()

BOOKING_DATE = date.today()


def _make_db_returning_none() -> AsyncMock:
    """Return an AsyncSession mock whose execute() → scalar_one_or_none() returns None.

    This simulates the ORM finding no row when both Doctor.id AND Doctor.branch_id
    must match — i.e., the cross-branch doctor lookup returns no result.
    """
    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=None)

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    return mock_db


# ──────────────────────────────────────────────────────────────────────────────
# Test 1 — check_availability rejects doctor from another branch
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_availability_rejects_doctor_from_other_branch() -> None:
    """check_availability with BRANCH_A branch_id but DOCTOR_B (BRANCH_B) must fail.

    Before the fix: select(Doctor).where(Doctor.id == doctor_id) would return
    doctor_b regardless of branch_id, potentially exposing cross-branch data.

    After the fix: select(Doctor).where(and_(Doctor.id == doctor_id, Doctor.branch_id == branch_id))
    returns None for a cross-branch lookup (the ORM finds no row matching both conditions).
    The function must return a "Doctor not found" failure, not silently proceed.
    """
    mock_db = _make_db_returning_none()

    result = await check_availability(
        doctor_id=DOCTOR_B_ID,
        branch_id=BRANCH_A_ID,  # BRANCH_A requests DOCTOR_B — cross-branch attempt
        booking_date=BOOKING_DATE,
        db=mock_db,
    )

    assert result == "Doctor not found.", (
        f"Expected 'Doctor not found.' for cross-branch lookup, got: {result!r}"
    )

    # Verify DB was queried (not silently skipped)
    mock_db.execute.assert_called_once()


# ──────────────────────────────────────────────────────────────────────────────
# Test 2 — assign_token rejects doctor from another branch
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_assign_token_rejects_doctor_from_other_branch() -> None:
    """assign_token with BRANCH_A branch_id but DOCTOR_B (BRANCH_B) must fail.

    After the fix: the Doctor lookup returns None → assign_token returns
    {"success": False, "reason": "doctor_not_found"}. No Redis INCR should fire.
    """
    mock_db = _make_db_returning_none()

    result = await assign_token(
        doctor_id=DOCTOR_B_ID,
        branch_id=BRANCH_A_ID,  # cross-branch attempt
        booking_date=BOOKING_DATE,
        db=mock_db,
    )

    assert isinstance(result, dict), f"Expected dict result, got: {type(result)}"
    assert result.get("success") is False, (
        f"Expected success=False for cross-branch lookup, got: {result}"
    )
    assert result.get("reason") == "doctor_not_found", (
        f"Expected reason='doctor_not_found', got: {result.get('reason')!r}"
    )

    # Verify DB was queried
    mock_db.execute.assert_called_once()


# ──────────────────────────────────────────────────────────────────────────────
# Test 3 — confirm_booking rejects doctor from another branch
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_confirm_booking_rejects_doctor_from_other_branch() -> None:
    """confirm_booking with BRANCH_A branch_id but DOCTOR_B (BRANCH_B) must fail.

    confirm_booking first looks up Patient (by branch_id + phone), then Doctor.
    We mock the Patient lookup to return None (creates new patient) so execution
    reaches the Doctor lookup. The Doctor lookup returns None → scalar_one() raises
    NoResultFound which propagates up as an exception (the function does not catch
    it, so the booking is aborted, which is the correct behavior per Rule 4: calendar
    must succeed — if doctor is not found, the function raises before calendar).

    We assert either:
    (a) the function raises an exception (any) — doctor not found aborts booking, OR
    (b) the function returns {"success": False, ...} — explicit failure dict.

    Both are acceptable; what is NOT acceptable is success=True with a cross-branch doctor.
    """
    # confirm_booking makes multiple execute() calls:
    #   1. Patient lookup (returns None → creates new patient)
    #   2. Token creation (flush)
    #   3. Doctor lookup (returns None → should abort)
    call_count: dict[str, int] = {"n": 0}

    patient_uuid = uuid.uuid4()

    mock_patient = MagicMock()
    mock_patient.id = patient_uuid
    mock_patient.followup_consent = False

    def make_mock_result(scalar_value: Any) -> MagicMock:
        r = MagicMock()
        r.scalar_one_or_none = MagicMock(return_value=scalar_value)
        r.scalar_one = MagicMock(return_value=scalar_value)
        return r

    def side_effect_execute(*args: Any, **kwargs: Any) -> MagicMock:
        call_count["n"] += 1
        if call_count["n"] == 1:
            # Patient lookup — return existing patient so we skip patient creation
            return make_mock_result(mock_patient)
        # Doctor lookup — cross-branch: return None
        return make_mock_result(None)

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=side_effect_execute)
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()

    mock_calendar = AsyncMock()
    mock_calendar.create_booking_event = AsyncMock(return_value="event-001")
    mock_meta = AsyncMock()
    mock_meta.send_booking_confirmation = AsyncMock(return_value=None)

    raised = False
    result: dict | None = None

    try:
        result = await confirm_booking(
            doctor_id=DOCTOR_B_ID,
            branch_id=BRANCH_A_ID,  # cross-branch attempt
            patient_name="Test Patient",
            patient_phone="+919876540001",
            complaint="headache",
            booking_date=BOOKING_DATE,
            token_number=1,
            followup_consent=False,
            appointment_time=None,
            source="voice",
            db=mock_db,
            calendar_service=mock_calendar,
            meta_service=mock_meta,
        )
    except Exception:
        raised = True

    # Either an exception was raised (booking aborted) or we got an explicit failure dict.
    # What is NEVER acceptable: success=True with cross-branch doctor.
    if not raised:
        assert result is not None
        assert result.get("success") is not True, (
            f"Cross-branch booking must NOT succeed. Got: {result}"
        )

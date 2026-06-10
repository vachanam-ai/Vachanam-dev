"""Unit tests for backend/services/booking_calendar.py.

Tests:
  1. test_token_doctor_enqueues_nothing
       — token-doctor path returns immediately; no CalendarWriteTask row created.
  2. test_slot_doctor_sync_success
       — slot-doctor + mock Cal succeeds inline → Token.google_calendar_event_id set,
         no CalendarWriteTask row.
  3. test_slot_doctor_sync_fail_falls_back_to_queue
       — slot-doctor + mock Cal raises CalendarWriteFailed on every attempt →
         exactly 1 CalendarWriteTask row with status='pending'.
  4. test_slot_doctor_no_calendar_id_enqueues_failed_permanent
       — slot-doctor + calendar_id=None → CalendarWriteTask row with
         status='failed_permanent' + admin_alert called once.

All tests that touch the DB use the `db` conftest fixture (test Postgres).
No real Google Calendar API calls are made — GoogleCalendarService is mock-patched.

See spec §6.7:
  docs/superpowers/specs/2026-06-08-calendar-and-receptionist-pwa-design.md
"""
from __future__ import annotations

import uuid
from datetime import date, time
from unittest.mock import AsyncMock, patch

import pytest

from backend.models.schema import (
    Branch,
    CalendarWriteTask,
    Doctor,
    Organization,
    Patient,
    Token,
)
from backend.services.booking_calendar import write_booking_calendar
from backend.services.calendar_service import CalendarWriteFailed


# ---------------------------------------------------------------------------
# Inline factory helpers — same pattern as test_calendar_writer_backoff.py
# No new conftest fixtures needed; all state is scoped to the test function.
# ---------------------------------------------------------------------------


async def _make_org_branch(db) -> tuple[Organization, Branch]:
    """Insert a minimal Org + Branch and return both (flushed, not committed)."""
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
    return org, branch


async def _make_token_doctor(db, branch: Branch) -> Doctor:
    """Insert a token-type Doctor and return it."""
    doctor = Doctor(
        branch_id=branch.id,
        name="Dr Token",
        booking_type="token",
        daily_token_limit=30,
    )
    db.add(doctor)
    await db.flush()
    return doctor


async def _make_slot_doctor(db, branch: Branch) -> Doctor:
    """Insert an appointment-type Doctor and return it."""
    doctor = Doctor(
        branch_id=branch.id,
        name="Dr Slot",
        booking_type="appointment",
        slot_duration_minutes=30,
    )
    db.add(doctor)
    await db.flush()
    return doctor


async def _make_patient(db, branch: Branch) -> Patient:
    """Insert a minimal Patient and return it."""
    patient = Patient(
        branch_id=branch.id,
        name="Test Patient",
        phone="+919876543210",
    )
    db.add(patient)
    await db.flush()
    return patient


async def _make_token(db, branch: Branch, doctor: Doctor, patient: Patient) -> Token:
    """Insert a Token (slot booking, appointment_time set) and return it."""
    token = Token(
        branch_id=branch.id,
        doctor_id=doctor.id,
        patient_id=patient.id,
        date=date(2026, 6, 20),
        appointment_time=time(10, 0),
        source="walk_in",
        token_number=1,
    )
    db.add(token)
    await db.commit()
    return token


# ---------------------------------------------------------------------------
# 1. Token-doctor: no CalendarWriteTask row created
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_token_doctor_enqueues_nothing(db) -> None:
    """token-doctor path must return immediately without writing any queue row."""
    _, branch = await _make_org_branch(db)
    doctor = await _make_token_doctor(db, branch)
    patient = await _make_patient(db, branch)
    token = await _make_token(db, branch, doctor, patient)

    await write_booking_calendar(
        db, token, doctor,
        calendar_id_or_none=None,
        patient_first_name="Test",
        patient_phone_last4="3210",
    )

    from sqlalchemy import select

    rows = (
        await db.execute(
            select(CalendarWriteTask).where(CalendarWriteTask.token_id == token.id)
        )
    ).all()
    assert len(rows) == 0, (
        f"Expected 0 CalendarWriteTask rows for token-doctor, got {len(rows)}"
    )


# ---------------------------------------------------------------------------
# 2. Slot-doctor sync success: event_id written to Token, no queue row
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_slot_doctor_sync_success(db) -> None:
    """slot-doctor + Cal mock returns event_id inline → Token.google_calendar_event_id
    set to the returned id; no CalendarWriteTask row created."""
    _, branch = await _make_org_branch(db)
    doctor = await _make_slot_doctor(db, branch)
    patient = await _make_patient(db, branch)
    token = await _make_token(db, branch, doctor, patient)

    with patch("backend.services.booking_calendar.GoogleCalendarService") as mock_cls:
        mock_instance = mock_cls.return_value
        mock_instance.create_booking_event = AsyncMock(return_value="evt_inline_123")

        await write_booking_calendar(
            db, token, doctor,
            calendar_id_or_none="cal_x",
            patient_first_name="Test",
            patient_phone_last4="3210",
        )

    await db.refresh(token)
    assert token.google_calendar_event_id == "evt_inline_123", (
        f"Expected 'evt_inline_123', got {token.google_calendar_event_id!r}"
    )

    # No queue row should exist — inline succeeded.
    from sqlalchemy import select

    rows = (
        await db.execute(
            select(CalendarWriteTask).where(CalendarWriteTask.token_id == token.id)
        )
    ).all()
    assert len(rows) == 0, (
        f"Expected 0 CalendarWriteTask rows after inline success, got {len(rows)}"
    )


# ---------------------------------------------------------------------------
# 3. Slot-doctor sync fail → falls back to queue with status='pending'
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_slot_doctor_sync_fail_falls_back_to_queue(db) -> None:
    """slot-doctor + Cal mock raises CalendarWriteFailed on all inline attempts →
    exactly 1 CalendarWriteTask row created with status='pending'."""
    _, branch = await _make_org_branch(db)
    doctor = await _make_slot_doctor(db, branch)
    patient = await _make_patient(db, branch)
    token = await _make_token(db, branch, doctor, patient)

    with (
        patch("backend.services.booking_calendar.GoogleCalendarService") as mock_cls,
        patch(
            "backend.services.booking_calendar.alert_admin",
            new_callable=AsyncMock,
        ),
        patch("backend.services.booking_calendar.asyncio.sleep", new_callable=AsyncMock),
    ):
        mock_instance = mock_cls.return_value
        mock_instance.create_booking_event = AsyncMock(
            side_effect=CalendarWriteFailed("boom")
        )

        await write_booking_calendar(
            db, token, doctor,
            calendar_id_or_none="cal_x",
            patient_first_name="Test",
            patient_phone_last4="3210",
        )

    from sqlalchemy import select

    rows = (
        await db.execute(
            select(CalendarWriteTask).where(CalendarWriteTask.token_id == token.id)
        )
    ).scalars().all()
    assert len(rows) == 1, (
        f"Expected exactly 1 CalendarWriteTask row after inline exhaustion, got {len(rows)}"
    )
    assert rows[0].status == "pending", (
        f"Expected status='pending', got {rows[0].status!r}"
    )


# ---------------------------------------------------------------------------
# 4. Slot-doctor, calendar_id=None → queue row with status='failed_permanent' + alert
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_slot_doctor_no_calendar_id_enqueues_failed_permanent(db) -> None:
    """slot-doctor + calendar_id=None → CalendarWriteTask with status='failed_permanent'
    and alert_admin called exactly once."""
    _, branch = await _make_org_branch(db)
    doctor = await _make_slot_doctor(db, branch)
    patient = await _make_patient(db, branch)
    token = await _make_token(db, branch, doctor, patient)

    with patch(
        "backend.services.booking_calendar.alert_admin",
        new_callable=AsyncMock,
    ) as mock_alert:
        await write_booking_calendar(
            db, token, doctor,
            calendar_id_or_none=None,
            patient_first_name="Test",
            patient_phone_last4="3210",
        )

    from sqlalchemy import select

    rows = (
        await db.execute(
            select(CalendarWriteTask).where(CalendarWriteTask.token_id == token.id)
        )
    ).scalars().all()
    assert len(rows) == 1, (
        f"Expected 1 CalendarWriteTask row for missing calendar_id, got {len(rows)}"
    )
    assert rows[0].status == "failed_permanent", (
        f"Expected status='failed_permanent', got {rows[0].status!r}"
    )

    mock_alert.assert_awaited_once()
    assert mock_alert.call_args.args[0] == "calendar_not_configured", (
        f"Expected event='calendar_not_configured', got {mock_alert.call_args.args[0]!r}"
    )

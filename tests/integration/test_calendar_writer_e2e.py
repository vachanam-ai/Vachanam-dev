"""Integration test: calendar_writer end-to-end against live Google Calendar.

SKIP REASON: Requires Vinay to share his Google Calendar with the Vachanam
service account (vachanam-events@vachanam-prod.iam.gserviceaccount.com) and
set GOOGLE_SA_JSON_B64 or point GOOGLE_APPLICATION_CREDENTIALS at the
service-account JSON.

See Task 1 Step 6 of:
  docs/superpowers/plans/2026-06-08-calendar-and-receptionist-pwa-plan.md

This test will be un-skipped once:
  1. Vinay completes Task 1 pre-flight (Cal share + env vars set).
  2. A live calendar_id is available in the test DB seed (Branch.google_calendar_id).

Wiring:
  - Creates a real CalendarWriteTask row via the `db` fixture.
  - Calls run_calendar_writer() once.
  - Asserts task.status == 'done' and google_calendar_event_id on Token.
  - Cleans up the Google Calendar event via delete_event.
"""

import pytest

pytest.skip(
    "requires live Google Cal — gated on Vinay's cal-share, see Task 1 Step 6 of "
    "docs/superpowers/plans/2026-06-08-calendar-and-receptionist-pwa-plan.md",
    allow_module_level=True,
)

# ── Real test body (runs only when un-skipped) ─────────────────────────────

import uuid
from datetime import date, time, datetime

from backend.jobs.calendar_writer import run_calendar_writer
from backend.models.schema import (
    Branch,
    CalendarWriteTask,
    Doctor,
    Organization,
    Patient,
    Token,
)
from backend.services.calendar_service import GoogleCalendarService


@pytest.mark.asyncio
async def test_calendar_writer_creates_and_marks_done(db) -> None:
    """Full round-trip: enqueue → run_calendar_writer → assert done + cleanup."""
    org = Organization(
        name="E2E Org",
        owner_phone="9000000001",
        owner_email=f"e2e_{uuid.uuid4().hex[:6]}@test.com",
        plan="clinic",
    )
    db.add(org)
    await db.flush()

    branch = Branch(
        org_id=org.id,
        name="E2E Branch",
        whatsapp_number="+919000000001",
        google_calendar_id="<REPLACE_WITH_REAL_CAL_ID>",
    )
    db.add(branch)
    await db.flush()

    doctor = Doctor(
        branch_id=branch.id,
        name="Dr E2E",
        booking_type="appointment",
        google_calendar_id=branch.google_calendar_id,
    )
    db.add(doctor)
    await db.flush()

    patient = Patient(branch_id=branch.id, name="E2E Patient", phone="+919876543210")
    db.add(patient)
    await db.flush()

    token = Token(
        branch_id=branch.id,
        doctor_id=doctor.id,
        patient_id=patient.id,
        date=date(2026, 6, 25),
        source="walk_in",
        appointment_time=time(11, 0),
    )
    db.add(token)
    await db.flush()

    task = CalendarWriteTask(
        branch_id=branch.id,
        token_id=token.id,
        operation="create",
        payload_json={
            "calendar_id": branch.google_calendar_id,
            "patient_first_name": "E2E",
            "patient_phone_last4": "3210",
            "appointment_dt": "2026-06-25T11:00:00",
            "duration_minutes": 30,
            "doctor_name": "Dr E2E",
        },
        status="pending",
        attempts=0,
    )
    db.add(task)
    await db.commit()

    # Run the worker
    await run_calendar_writer()

    await db.refresh(task)
    await db.refresh(token)

    assert task.status == "done"
    assert task.google_event_id is not None
    assert token.google_calendar_event_id == task.google_event_id

    # Cleanup: delete the event from real Google Calendar
    svc = GoogleCalendarService()
    await svc.delete_event(branch.google_calendar_id, task.google_event_id)

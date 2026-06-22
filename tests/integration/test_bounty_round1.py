"""Regression guards for bug-bounty round 1 (docs/bugbounty/round1.md).

B1: cascade calendar-delete tasks carried calendar_id=None and the writer
    used it verbatim -> every cascade calendar delete failed permanently.
B5: reminder window compared bare time() objects; near midnight lo > hi and
    nothing ever matched -> late-night reminders silently skipped.
B6: _resolve_doctor_id substring name match returned the FIRST of multiple
    matches -> booking could attach to the wrong doctor.
"""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from sqlalchemy import select

from agent.session_state import SessionState
from backend.models.schema import (
    Branch,
    CalendarWriteTask,
    Doctor,
    Organization,
    Patient,
    Token,
)

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def clinic(db):
    org = Organization(
        name="Bounty Clinic",
        owner_phone="+919999999977",
        owner_email="bounty1@clinic.test",
        plan="clinic",
        status="active",
    )
    db.add(org)
    await db.flush()
    branch = Branch(
        org_id=org.id,
        name="Bounty Branch",
        whatsapp_number="+911111111133",
        did_number="+912222222244",
        google_calendar_id="branch-cal@group.calendar.google.com",
        status="active",
    )
    db.add(branch)
    await db.flush()
    doc = Doctor(
        branch_id=branch.id,
        name="Dr. Bounty",
        specialization="dermatology",
        routing_keywords=["skin"],
        booking_type="appointment",
        working_hours_start=time(9, 0),
        working_hours_end=time(17, 0),
        slot_duration_minutes=30,
        google_calendar_id="doctor-cal@group.calendar.google.com",
        status="active",
    )
    db.add(doc)
    await db.commit()
    return {"org": org, "branch": branch, "doc": doc}


# ── B1: calendar delete must resolve a real calendar id ─────────────────────


class _CaptureSvc:
    def __init__(self):
        self.deleted = []

    async def delete_event(self, calendar_id, event_id):
        self.deleted.append((calendar_id, event_id))


async def test_cascade_delete_resolves_calendar_id(clinic, db):
    from backend.jobs.calendar_writer import _process_one_task

    branch, doc = clinic["branch"], clinic["doc"]
    patient = Patient(branch_id=branch.id, name="Cal Victim", phone="+919666444412")
    db.add(patient)
    await db.flush()
    token = Token(
        branch_id=branch.id,
        doctor_id=doc.id,
        patient_id=patient.id,
        date=date.today() + timedelta(days=1),
        token_number=1,
        appointment_time=time(10, 0),
        source="voice",
        status="cancelled_by_clinic",
        google_calendar_event_id="evt-ghost-1",
    )
    db.add(token)
    await db.flush()
    # exactly what cascade_cancel enqueues: calendar_id None in the payload
    task = CalendarWriteTask(
        branch_id=branch.id,
        token_id=token.id,
        operation="delete",
        payload_json={"calendar_id": None, "google_event_id": "evt-ghost-1"},
        google_event_id="evt-ghost-1",
        status="pending",
        attempts=0,
        next_attempt_at=datetime.now(timezone.utc),
    )
    db.add(task)
    await db.commit()

    svc = _CaptureSvc()
    await _process_one_task(db, task, svc)

    assert task.status == "done", task.last_error
    # resolved from the token's DOCTOR calendar (falls back to branch)
    assert svc.deleted == [("doctor-cal@group.calendar.google.com", "evt-ghost-1")]


# ── B5: reminder window survives midnight ────────────────────────────────────


def test_reminder_window_midnight_wrap():
    from backend.jobs.pre_appt_reminder import appointment_in_window, reminder_window

    tz = ZoneInfo("Asia/Kolkata")
    # 23:50 — the resilient window [now, now+31min] lands at 23:50-00:21 NEXT day
    now = datetime(2026, 6, 12, 23, 50, tzinfo=tz)
    lo, hi = reminder_window(now)
    assert lo.date() != now.date() or hi.date() != now.date()  # crosses midnight
    # appointment tomorrow 00:19 IS in the window (old time-only compare missed it)
    assert appointment_in_window(date(2026, 6, 13), time(0, 19), lo, hi) is True
    # resilient window (#149): a near appointment 23:55 (5 min away) IS now in the
    # window — we fire late rather than drop it; the old 28-31 band excluded it.
    assert appointment_in_window(date(2026, 6, 12), time(23, 55), lo, hi) is True
    # an appointment >31 min out (00:30, 40 min away) is NOT yet in the window
    assert appointment_in_window(date(2026, 6, 13), time(0, 30), lo, hi) is False
    # a past appointment (23:45, already started) is excluded
    assert appointment_in_window(date(2026, 6, 12), time(23, 45), lo, hi) is False


def test_reminder_window_normal_afternoon():
    from backend.jobs.pre_appt_reminder import appointment_in_window, reminder_window

    tz = ZoneInfo("Asia/Kolkata")
    now = datetime(2026, 6, 12, 15, 45, tzinfo=tz)
    lo, hi = reminder_window(now)
    # 28-31 min window = 16:13-16:16
    assert appointment_in_window(date(2026, 6, 12), time(16, 15), lo, hi) is True
    assert appointment_in_window(date(2026, 6, 12), time(16, 30), lo, hi) is False
    assert appointment_in_window(date(2026, 6, 12), None, lo, hi) is False


# ── B6: ambiguous doctor name must never silently pick one ──────────────────


async def test_resolve_doctor_id_ambiguous_name_refuses(clinic, db):
    from livekit.agents import ToolError as _ToolError

    from agent.livekit_minimal.agent import VachanamAgent

    branch = clinic["branch"]
    db.add_all(
        [
            Doctor(
                branch_id=branch.id, name="Test Kumar", specialization="dentistry",
                routing_keywords=["tooth"], booking_type="token", status="active",
            ),
            Doctor(
                branch_id=branch.id, name="Ravi Kumar", specialization="cardiology",
                routing_keywords=["heart"], booking_type="token", status="active",
            ),
        ]
    )
    await db.commit()

    state = SessionState(session_id="b6")
    state.branch_id = branch.id
    agent = VachanamAgent(
        instructions="t", state=state, db=db, room=None,
        calendar_service=None, meta_service=None, transfer_to="",
    )
    with pytest.raises(_ToolError, match="multiple doctors"):
        await agent._resolve_doctor_id("Dr. Kumar")
    # unambiguous name still resolves
    resolved = await agent._resolve_doctor_id("Ravi Kumar")
    doc = (await db.execute(select(Doctor).where(Doctor.id == resolved))).scalar_one()
    assert doc.name == "Ravi Kumar"

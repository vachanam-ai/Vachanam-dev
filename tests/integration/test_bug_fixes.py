"""Proof tests for the 2026-06-12 bug-hunt fixes.

Bug 2: confirm_booking's function-level @retry re-ran the whole function on a
       transient calendar failure; the session still held attempt #1's pending
       Token, so attempt #2 inserted a duplicate. Fix: retry wraps only the
       calendar write. Proven by: transient calendar failure -> success with
       EXACTLY ONE token row.

Bug 3: cancelling a token-doctor booking DECR'd the Redis token counter, so
       the next patient received the SAME queue number as the cancelled one
       (and DECR on a missing key issues token 0). Fix: token counters are
       never decremented. Proven by: cancel then assign -> strictly higher
       token number.

Bug 1: LLM-orchestrated reschedules kept cancelling without booking (or
       booking without cancelling — Vinay's June 14 double). Fix: atomic
       _do_reschedule. Proven by: one call leaves exactly one confirmed
       booking on the new date and the old one cancelled; impossible date ->
       old booking untouched.
"""
from datetime import date, time, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import and_, func, select

from agent.session_state import SessionState
from agent.tools.booking_tools import assign_token, confirm_booking
from backend.models.schema import Branch, Doctor, Organization, Patient, Token

pytestmark = pytest.mark.asyncio


class FlakyCalendar:
    """Fails N times, then returns event ids. Triggers the old duplicate bug."""

    def __init__(self, failures: int):
        self.failures = failures
        self.calls = 0

    async def create_booking_event(self, **kw) -> str:
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("transient calendar 503")
        return f"evt-{self.calls}"

    async def delete_event(self, calendar_id, event_id) -> None:
        return None


class NullMeta:
    async def send_booking_confirmation(self, **kw):
        return None


@pytest_asyncio.fixture
async def clinic(db):
    org = Organization(
        name="Bugfix Clinic",
        owner_phone="+919999999988",
        owner_email="bugfix@clinic.test",
        plan="clinic",
        status="active",
    )
    db.add(org)
    await db.flush()
    branch = Branch(
        org_id=org.id,
        name="Bugfix Branch",
        whatsapp_number="+911111111122",
        did_number="+912222222233",
        emergency_contact="+913333333344",
        status="active",
    )
    db.add(branch)
    await db.flush()
    token_doc = Doctor(
        branch_id=branch.id,
        name="Dr. Token",
        specialization="general_physician",
        routing_keywords=["fever"],
        is_default_doctor=True,
        booking_type="token",
        daily_token_limit=20,
        status="active",
    )
    slot_doc = Doctor(
        branch_id=branch.id,
        name="Dr. Slots",
        specialization="dermatology",
        routing_keywords=["skin"],
        booking_type="appointment",
        working_hours_start=time(9, 0),
        working_hours_end=time(17, 0),
        slot_duration_minutes=30,
        max_concurrent_per_slot=1,
        status="active",
    )
    db.add_all([token_doc, slot_doc])
    await db.commit()
    return {"branch": branch, "token_doc": token_doc, "slot_doc": slot_doc}


def _tomorrow() -> date:
    d = date.today() + timedelta(days=1)
    # land on a working weekday for default Mon-Sat doctors
    while d.weekday() == 6:
        d += timedelta(days=1)
    return d


async def _count_tokens(db, doctor_id, branch_id, day) -> int:
    return (
        await db.execute(
            select(func.count()).select_from(Token).where(
                and_(
                    Token.doctor_id == doctor_id,
                    Token.branch_id == branch_id,
                    Token.date == day,
                )
            )
        )
    ).scalar_one()


# ── Bug 2: transient calendar failure must NOT duplicate bookings ────────────


async def test_confirm_booking_transient_calendar_failure_single_row(clinic, db, redis):
    branch, doc = clinic["branch"], clinic["token_doc"]
    day = _tomorrow()
    assigned = await assign_token(doc.id, branch.id, day, db)
    assert assigned["success"]

    cal = FlakyCalendar(failures=2)  # fails twice, succeeds third time
    result = await confirm_booking(
        doctor_id=doc.id,
        branch_id=branch.id,
        patient_name="Retry Proof",
        patient_phone="+919666444428",
        complaint="fever",
        booking_date=day,
        token_number=assigned["token_number"],
        followup_consent=False,
        appointment_time=None,
        source="voice",
        db=db,
        calendar_service=cal,
        meta_service=NullMeta(),
    )
    assert result["success"], result
    assert cal.calls == 3  # retried inside the calendar step only
    assert await _count_tokens(db, doc.id, branch.id, day) == 1  # ONE row, not 2/3


# ── Bug 3: cancelled token numbers are never reissued ────────────────────────


async def test_cancelled_token_number_never_reissued(clinic, db, redis):
    from agent.livekit_minimal.agent import VachanamAgent

    branch, doc = clinic["branch"], clinic["token_doc"]
    day = _tomorrow()

    first = await assign_token(doc.id, branch.id, day, db)
    assert first["token_number"] == 1
    confirmed = await confirm_booking(
        doctor_id=doc.id,
        branch_id=branch.id,
        patient_name="Number One",
        patient_phone="+919666444428",
        complaint="fever",
        booking_date=day,
        token_number=1,
        followup_consent=False,
        appointment_time=None,
        source="voice",
        db=db,
        calendar_service=FlakyCalendar(failures=0),
        meta_service=NullMeta(),
    )
    assert confirmed["success"]

    state = SessionState(session_id="t")
    state.branch_id = branch.id
    state.token_confirmed = True
    agent = VachanamAgent(
        instructions="t",
        state=state,
        db=db,
        room=None,
        calendar_service=None,
        meta_service=NullMeta(),
        transfer_to="",
    )
    cancel = await agent._do_cancel(confirmed["token_id"])
    assert cancel["success"]

    # The cancelled patient held number 1; the next patient must get 2 — the
    # old DECR behaviour would have reissued number 1 to a different person.
    second = await assign_token(doc.id, branch.id, day, db)
    assert second["success"]
    assert second["token_number"] == 2


# ── Bug 1: reschedule is atomic — never leaves two confirmed bookings ────────


async def test_reschedule_atomic_one_confirmed_booking(clinic, db, redis):
    from agent.livekit_minimal.agent import VachanamAgent

    branch, doc = clinic["slot_doc"], None
    branch, doc = clinic["branch"], clinic["slot_doc"]
    day = _tomorrow()

    assigned = await assign_token(doc.id, branch.id, day, db, appointment_time=time(10, 0))
    assert assigned["success"], assigned
    confirmed = await confirm_booking(
        doctor_id=doc.id,
        branch_id=branch.id,
        patient_name="Resched Proof",
        patient_phone="+919666444428",
        complaint="skin",
        booking_date=day,
        token_number=assigned["token_number"],
        followup_consent=False,
        appointment_time=time(10, 0),
        source="voice",
        db=db,
        calendar_service=FlakyCalendar(failures=0),
        meta_service=NullMeta(),
    )
    assert confirmed["success"]

    state = SessionState(session_id="t2")
    state.branch_id = branch.id
    agent = VachanamAgent(
        instructions="t",
        state=state,
        db=db,
        room=None,
        calendar_service=FlakyCalendar(failures=0),
        meta_service=NullMeta(),
        transfer_to="",
    )
    result = await agent._do_reschedule(confirmed["token_id"], day.isoformat(), "11:00")
    assert result["success"], result
    assert result["old_cancelled"] is True

    rows = (
        await db.execute(
            select(Token.appointment_time, Token.status).where(
                and_(Token.doctor_id == doc.id, Token.branch_id == branch.id, Token.date == day)
            )
        )
    ).all()
    confirmed_rows = [r for r in rows if r.status == "confirmed"]
    assert len(confirmed_rows) == 1  # exactly one live booking
    assert confirmed_rows[0].appointment_time == time(11, 0)


async def test_reschedule_failure_keeps_old_booking(clinic, db, redis):
    from agent.livekit_minimal.agent import VachanamAgent

    branch, doc = clinic["branch"], clinic["slot_doc"]
    day = _tomorrow()

    assigned = await assign_token(doc.id, branch.id, day, db, appointment_time=time(12, 0))
    confirmed = await confirm_booking(
        doctor_id=doc.id,
        branch_id=branch.id,
        patient_name="Keep Me",
        patient_phone="+919666444428",
        complaint="skin",
        booking_date=day,
        token_number=assigned["token_number"],
        followup_consent=False,
        appointment_time=time(12, 0),
        source="voice",
        db=db,
        calendar_service=FlakyCalendar(failures=0),
        meta_service=NullMeta(),
    )
    assert confirmed["success"]

    state = SessionState(session_id="t3")
    state.branch_id = branch.id
    agent = VachanamAgent(
        instructions="t",
        state=state,
        db=db,
        room=None,
        calendar_service=FlakyCalendar(failures=0),
        meta_service=NullMeta(),
        transfer_to="",
    )
    # past date -> assign step refuses -> old booking must stay confirmed
    past = (date.today() - timedelta(days=1)).isoformat()
    result = await agent._do_reschedule(confirmed["token_id"], past, "11:00")
    assert result["success"] is False
    assert result["step"] == "assign"

    from uuid import UUID as _UUID

    old = (
        await db.execute(select(Token).where(Token.id == _UUID(confirmed["token_id"])))
    ).scalar_one()
    assert old.status == "confirmed"  # patient still has their booking

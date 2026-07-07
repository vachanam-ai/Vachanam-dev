"""Torture suite for booking/reschedule state machine (FIXLOG #286).

Vinay 2026-07-07: "repeat same requests, tell one time, immediately tell
another, come back to the first spoken time, reschedule, immediately give
another time, repeat the same things multiple times — torture it end to end."

Every prod failure so far (#279/#281/#283/#284) lived in the TOOL/STATE layer,
so this suite drives the exact tool-call sequences the LLM emits for those
conversation patterns. Slot doctor has max_concurrent_per_slot=1 — the
tightest capacity, where own-booking shadowing bugs show up.
"""
import uuid
from datetime import date, time, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import and_, select

from agent.livekit_minimal.agent import VachanamAgent
from agent.session_state import SessionState
from agent.tools.booking_tools import assign_token, check_availability, confirm_booking
from backend.models.schema import Branch, Doctor, Organization, Token

pytestmark = pytest.mark.asyncio

CALLER = "+919666777001"


class OkCalendar:
    async def create_booking_event(self, **kw) -> str:
        return f"evt-{uuid.uuid4().hex[:6]}"

    async def delete_event(self, calendar_id, event_id) -> None:
        return None


class NullMeta:
    async def send_booking_confirmation(self, **kw):
        return None


def _tomorrow() -> date:
    d = date.today() + timedelta(days=1)
    while d.weekday() == 6:
        d += timedelta(days=1)
    return d


@pytest_asyncio.fixture
async def clinic(db):
    org = Organization(name="Torture Clinic", owner_phone="+919999000088",
                       owner_email=f"torture-{uuid.uuid4().hex[:6]}@clinic.test",
                       plan="clinic", status="active")
    db.add(org)
    await db.flush()
    branch = Branch(org_id=org.id, name="Torture Branch",
                    whatsapp_number=f"+9111{uuid.uuid4().hex[:8]}", status="active")
    db.add(branch)
    await db.flush()
    doc = Doctor(
        branch_id=branch.id, name="Dr. Torture", specialization="dermatology",
        routing_keywords=["skin"], is_default_doctor=True,
        booking_type="appointment", working_hours_start=time(9, 0),
        working_hours_end=time(17, 0), slot_duration_minutes=30,
        max_concurrent_per_slot=1, status="active",
    )
    db.add(doc)
    await db.commit()
    return {"branch": branch, "doc": doc}


def _agent(db, branch_id):
    state = SessionState(session_id="torture")
    state.branch_id = branch_id
    state.patient_phone = CALLER
    return VachanamAgent(
        instructions="t", state=state, db=db, room=None,
        calendar_service=OkCalendar(), meta_service=NullMeta(), transfer_to="",
    ), state


async def _book(db, branch, doc, at: time, day=None, name="Torture Vinay"):
    day = day or _tomorrow()
    assigned = await assign_token(doc.id, branch.id, day, db, appointment_time=at)
    assert assigned["success"], assigned
    confirmed = await confirm_booking(
        doctor_id=doc.id, branch_id=branch.id, patient_name=name,
        patient_phone=CALLER, complaint="skin", booking_date=day,
        token_number=assigned["token_number"], followup_consent=False,
        patient_age=30, appointment_time=at, source="voice", db=db,
        calendar_service=OkCalendar(), meta_service=NullMeta(),
    )
    assert confirmed["success"], confirmed
    return confirmed


async def _confirmed_rows(db, doc, branch, day):
    rows = (await db.execute(
        select(Token).where(and_(
            Token.doctor_id == doc.id, Token.branch_id == branch.id,
            Token.date == day, Token.status == "confirmed",
        ))
    )).scalars().all()
    return rows


# ── 1. flip-flop: A → B → back to A (come back to first spoken time) ──────

async def test_flipflop_back_to_original_time(clinic, db, redis):
    branch, doc = clinic["branch"], clinic["doc"]
    day = _tomorrow()
    booked = await _book(db, branch, doc, time(10, 0))
    agent, _ = _agent(db, branch.id)

    r1 = await agent._do_reschedule(booked["token_id"], day.isoformat(), "11:00")
    assert r1["success"], r1
    # come BACK to the first spoken time — the freed 10:00 must be re-bookable
    r2 = await agent._do_reschedule(booked["token_id"], day.isoformat(), "10:00")
    assert r2["success"], r2

    rows = await _confirmed_rows(db, doc, branch, day)
    assert len(rows) == 1
    assert rows[0].appointment_time == time(10, 0)


# ── 2. repeat the SAME time: reschedule to the slot they're already at ─────

async def test_reschedule_to_own_current_time_is_graceful(clinic, db, redis):
    """Caller repeats the time they already hold ("12:30కి మార్చండి" when the
    booking IS at 12:30). Their own row must not shadow the slot into 'full';
    the move must succeed (no-op) leaving exactly one confirmed booking."""
    branch, doc = clinic["branch"], clinic["doc"]
    day = _tomorrow()
    booked = await _book(db, branch, doc, time(12, 30))
    agent, _ = _agent(db, branch.id)

    r = await agent._do_reschedule(booked["token_id"], day.isoformat(), "12:30")
    assert r["success"], r

    rows = await _confirmed_rows(db, doc, branch, day)
    assert len(rows) == 1
    assert rows[0].appointment_time == time(12, 30)


# ── 3. identical reschedule repeated (LLM fires the tool twice) ────────────

async def test_same_reschedule_repeated_is_idempotent(clinic, db, redis):
    branch, doc = clinic["branch"], clinic["doc"]
    day = _tomorrow()
    booked = await _book(db, branch, doc, time(10, 0))
    agent, _ = _agent(db, branch.id)

    r1 = await agent._do_reschedule(booked["token_id"], day.isoformat(), "11:00")
    assert r1["success"], r1
    # repeat the exact same request (stale id + same target time)
    r2 = await agent._do_reschedule(booked["token_id"], day.isoformat(), "11:00")
    assert r2["success"], r2

    rows = await _confirmed_rows(db, doc, branch, day)
    assert len(rows) == 1
    assert rows[0].appointment_time == time(11, 0)


# ── 4. rapid chain of changes, ending on the first time ────────────────────

async def test_five_reschedules_chain_ends_clean(clinic, db, redis):
    branch, doc = clinic["branch"], clinic["doc"]
    day = _tomorrow()
    booked = await _book(db, branch, doc, time(10, 0))
    agent, _ = _agent(db, branch.id)

    for t in ("11:00", "12:00", "13:00", "14:00", "10:00"):
        r = await agent._do_reschedule(booked["token_id"], day.isoformat(), t)
        assert r["success"], (t, r)

    rows = await _confirmed_rows(db, doc, branch, day)
    assert len(rows) == 1
    assert rows[0].appointment_time == time(10, 0)
    # every superseded booking is cancelled_by_patient — never resurfaces
    all_rows = (await db.execute(
        select(Token).where(and_(
            Token.doctor_id == doc.id, Token.branch_id == branch.id,
            Token.date == day, Token.status != "confirmed",
        ))
    )).scalars().all()
    assert all(t.status == "cancelled_by_patient" for t in all_rows)


# ── 5. repeat the same BOOKING request (double confirm) ────────────────────

async def test_double_confirm_same_booking_no_duplicate(clinic, db, redis):
    branch, doc = clinic["branch"], clinic["doc"]
    day = _tomorrow()
    await _book(db, branch, doc, time(15, 0))

    # LLM repeats the whole flow for the same patient+day (caller repeated
    # themselves) — dup guard must refuse, not double-book.
    assigned = await assign_token(doc.id, branch.id, day, db, appointment_time=time(15, 30))
    assert assigned["success"]
    second = await confirm_booking(
        doctor_id=doc.id, branch_id=branch.id, patient_name="Torture Vinay",
        patient_phone=CALLER, complaint="skin", booking_date=day,
        token_number=assigned["token_number"], followup_consent=False,
        patient_age=30, appointment_time=time(15, 30), source="voice", db=db,
        calendar_service=OkCalendar(), meta_service=NullMeta(),
    )
    assert second["success"] is False
    assert second["reason"] == "already_booked"
    assert len(await _confirmed_rows(db, doc, branch, day)) == 1


# ── 6. book → cancel → immediately rebook the SAME slot ────────────────────

async def test_cancel_then_rebook_same_slot_immediately(clinic, db, redis):
    branch, doc = clinic["branch"], clinic["doc"]
    day = _tomorrow()
    booked = await _book(db, branch, doc, time(16, 0))
    agent, state = _agent(db, branch.id)
    state.token_confirmed = True

    cancel = await agent._do_cancel(booked["token_id"])
    assert cancel["success"], cancel

    rebooked = await _book(db, branch, doc, time(16, 0))
    assert rebooked["success"]
    rows = await _confirmed_rows(db, doc, branch, day)
    assert len(rows) == 1 and rows[0].appointment_time == time(16, 0)


# ── 7. reschedule into a FULL slot: old booking untouched ──────────────────

async def test_reschedule_to_full_slot_keeps_old_booking(clinic, db, redis):
    branch, doc = clinic["branch"], clinic["doc"]
    day = _tomorrow()
    # someone else holds 11:00 (capacity 1)
    other_assigned = await assign_token(doc.id, branch.id, day, db, appointment_time=time(11, 0))
    other = await confirm_booking(
        doctor_id=doc.id, branch_id=branch.id, patient_name="Other Person",
        patient_phone="+919666777002", complaint="skin", booking_date=day,
        token_number=other_assigned["token_number"], followup_consent=False,
        patient_age=40, appointment_time=time(11, 0), source="voice", db=db,
        calendar_service=OkCalendar(), meta_service=NullMeta(),
    )
    assert other["success"]

    booked = await _book(db, branch, doc, time(10, 0))
    agent, _ = _agent(db, branch.id)
    r = await agent._do_reschedule(booked["token_id"], day.isoformat(), "11:00")
    assert r["success"] is False  # full — clean refusal

    rows = await _confirmed_rows(db, doc, branch, day)
    times = sorted(t.appointment_time for t in rows)
    assert times == [time(10, 0), time(11, 0)]  # old booking untouched


# ── 8. cross-date flip-flop ────────────────────────────────────────────────

async def test_cross_date_reschedule_and_back(clinic, db, redis):
    branch, doc = clinic["branch"], clinic["doc"]
    day1 = _tomorrow()
    day2 = day1 + timedelta(days=1)
    while day2.weekday() == 6:
        day2 += timedelta(days=1)
    booked = await _book(db, branch, doc, time(10, 0), day=day1)
    agent, _ = _agent(db, branch.id)

    r1 = await agent._do_reschedule(booked["token_id"], day2.isoformat(), "10:00")
    assert r1["success"], r1
    r2 = await agent._do_reschedule(booked["token_id"], day1.isoformat(), "10:00")
    assert r2["success"], r2

    d1_rows = await _confirmed_rows(db, doc, branch, day1)
    d2_rows = await _confirmed_rows(db, doc, branch, day2)
    assert len(d1_rows) == 1 and d1_rows[0].appointment_time == time(10, 0)
    assert d2_rows == []


# ── 9. availability reflects a reschedule instantly ────────────────────────

async def test_availability_updates_after_reschedule(clinic, db, redis):
    branch, doc = clinic["branch"], clinic["doc"]
    day = _tomorrow()
    booked = await _book(db, branch, doc, time(10, 0))
    agent, _ = _agent(db, branch.id)
    r = await agent._do_reschedule(booked["token_id"], day.isoformat(), "11:00")
    assert r["success"], r

    # the freed 10:00 must read available; the new 11:00 must read taken
    free = await check_availability(doc.id, branch.id, day, db,
                                    query_start=time(10, 0), query_end=time(10, 30))
    assert "NOT free" not in free
    taken = await check_availability(doc.id, branch.id, day, db,
                                     query_start=time(11, 0), query_end=time(11, 30))
    assert "NOT free" in taken

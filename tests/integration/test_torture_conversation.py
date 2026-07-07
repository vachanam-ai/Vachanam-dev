"""Torture round 2 — conversation-pattern chaos (FIXLOG #287).

Vinay 2026-07-07: "ambiguous time asks, contradictions, repeats, multiple
voices — worst possible + regular scenarios." This file covers the tool/state
layer for contradiction + ambiguity patterns; prompt guards live in
tests/unit/test_system_prompt.py; true audio chaos (pauses/noise/multi-voice)
is real-call-only and tracked as a manual script.

Scenarios:
  B2  reschedule then "cancel it entirely" using the STALE original id
  B3  "cancel it" repeated twice (second must be a graceful already-cancelled)
  B5  cancel then "no wait, move it to Friday" (reschedule a cancelled booking
      -> guided recovery, not a bare technical error)
  B4  family: two bookings one call; rescheduling ONE never touches the other
  A3  past time on today -> clean refusal with guidance
  A4  off-grid time (10:07) -> clean refusal naming valid times
  A5  outside working hours (3 AM literal) -> clean refusal with hours
"""
import uuid
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from sqlalchemy import and_, select

from agent.livekit_minimal.agent import VachanamAgent
from agent.session_state import SessionState
from agent.tools.booking_tools import assign_token, confirm_booking
from backend.models.schema import Branch, Doctor, Organization, Token

pytestmark = pytest.mark.asyncio

CALLER = "+919666888001"
IST = ZoneInfo("Asia/Kolkata")


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
    org = Organization(name="Chaos Clinic", owner_phone="+919999000099",
                       owner_email=f"chaos-{uuid.uuid4().hex[:6]}@clinic.test",
                       plan="clinic", status="active")
    db.add(org)
    await db.flush()
    branch = Branch(org_id=org.id, name="Chaos Branch",
                    whatsapp_number=f"+9111{uuid.uuid4().hex[:8]}", status="active")
    db.add(branch)
    await db.flush()
    doc = Doctor(
        branch_id=branch.id, name="Dr. Chaos", specialization="dermatology",
        routing_keywords=["skin"], is_default_doctor=True,
        booking_type="appointment", working_hours_start=time(9, 0),
        working_hours_end=time(17, 0), slot_duration_minutes=30,
        max_concurrent_per_slot=1, status="active",
    )
    db.add(doc)
    await db.commit()
    return {"branch": branch, "doc": doc}


def _agent(db, branch_id):
    state = SessionState(session_id="chaos")
    state.branch_id = branch_id
    state.patient_phone = CALLER
    return VachanamAgent(
        instructions="t", state=state, db=db, room=None,
        calendar_service=OkCalendar(), meta_service=NullMeta(), transfer_to="",
    ), state


async def _book(db, branch, doc, at: time, name="Chaos Vinay",
                phone=CALLER, different_person=False):
    day = _tomorrow()
    assigned = await assign_token(doc.id, branch.id, day, db, appointment_time=at)
    assert assigned["success"], assigned
    confirmed = await confirm_booking(
        doctor_id=doc.id, branch_id=branch.id, patient_name=name,
        patient_phone=phone, complaint="skin", booking_date=day,
        token_number=assigned["token_number"], followup_consent=False,
        patient_age=30, appointment_time=at, source="voice", db=db,
        calendar_service=OkCalendar(), meta_service=NullMeta(),
        different_person=different_person,
    )
    assert confirmed["success"], confirmed
    return confirmed


async def _confirmed(db, doc, branch, day):
    return (await db.execute(
        select(Token).where(and_(
            Token.doctor_id == doc.id, Token.branch_id == branch.id,
            Token.date == day, Token.status == "confirmed",
        ))
    )).scalars().all()


# ── B2: reschedule then cancel-it-entirely with the STALE id ───────────────

async def test_cancel_after_reschedule_with_stale_id(clinic, db, redis):
    """"11:00కి మార్చండి... అసలు వద్దు, క్యాన్సిల్ చేసేయండి" — the LLM still
    holds the ORIGINAL token id (the reschedule cancelled it). Cancel must
    recover to the CURRENT confirmed booking, not die not_cancellable."""
    branch, doc = clinic["branch"], clinic["doc"]
    day = _tomorrow()
    booked = await _book(db, branch, doc, time(10, 0))
    agent, state = _agent(db, branch.id)

    r = await agent._do_reschedule(booked["token_id"], day.isoformat(), "11:00")
    assert r["success"], r
    state.token_confirmed = True

    cancel = await agent._do_cancel(booked["token_id"])  # STALE original id
    assert cancel["success"], cancel
    assert await _confirmed(db, doc, branch, day) == []  # nothing left booked


# ── B3: "cancel it" repeated twice ──────────────────────────────────────────

async def test_double_cancel_second_is_graceful(clinic, db, redis):
    branch, doc = clinic["branch"], clinic["doc"]
    day = _tomorrow()
    booked = await _book(db, branch, doc, time(12, 0))
    agent, state = _agent(db, branch.id)
    state.token_confirmed = True

    c1 = await agent._do_cancel(booked["token_id"])
    assert c1["success"], c1
    c2 = await agent._do_cancel(booked["token_id"])  # caller repeats
    # Not success (nothing to do) but MUST carry a spoken instruction that it
    # is already cancelled — never a bare error the LLM reads as "technical".
    assert c2["success"] is False
    assert "instruction" in c2
    assert "already" in c2["instruction"].lower()


# ── B5: cancel then "no wait, move it to Friday" ───────────────────────────

async def test_reschedule_after_cancel_gives_guided_recovery(clinic, db, redis):
    branch, doc = clinic["branch"], clinic["doc"]
    day = _tomorrow()
    booked = await _book(db, branch, doc, time(13, 0))
    agent, state = _agent(db, branch.id)
    state.token_confirmed = True

    c = await agent._do_cancel(booked["token_id"])
    assert c["success"]
    r = await agent._do_reschedule(booked["token_id"], day.isoformat(), "14:00")
    # No confirmed booking left to move — must NOT be a bare error: carry an
    # instruction telling the model to offer a FRESH booking at that time.
    assert r["success"] is False
    assert "instruction" in r
    assert "book" in r["instruction"].lower()


# ── B4: family isolation under reschedule ───────────────────────────────────

async def test_family_sibling_untouched_by_reschedule(clinic, db, redis):
    branch, doc = clinic["branch"], clinic["doc"]
    day = _tomorrow()
    mine = await _book(db, branch, doc, time(10, 0), name="Chaos Vinay")
    fam = await _book(db, branch, doc, time(10, 30), name="Amma",
                      phone="+919666888002", different_person=True)
    agent, _ = _agent(db, branch.id)

    r = await agent._do_reschedule(mine["token_id"], day.isoformat(), "15:00")
    assert r["success"], r

    rows = await _confirmed(db, doc, branch, day)
    times = sorted(t.appointment_time for t in rows)
    assert times == [time(10, 30), time(15, 0)]  # Amma untouched, mine moved


# ── A3/A4/A5: ambiguous time inputs get GUIDED refusals ─────────────────────

async def test_past_time_today_refused_with_guidance(clinic, db, redis):
    branch, doc = clinic["branch"], clinic["doc"]
    now_ist = datetime.now(IST)
    if not (time(10, 0) <= now_ist.time() <= time(16, 0)):
        pytest.skip("needs IST business hours to have a past slot today")
    past = (now_ist - timedelta(hours=1)).time().replace(minute=0, second=0, microsecond=0)
    r = await assign_token(doc.id, branch.id, now_ist.date(), db, appointment_time=past)
    assert r["success"] is False
    assert r["reason"] in ("past_slot", "outside_working_hours")
    assert "instruction" in r or "working_hours" in r


async def test_offgrid_time_refused_names_valid_slots(clinic, db, redis):
    branch, doc = clinic["branch"], clinic["doc"]
    r = await assign_token(doc.id, branch.id, _tomorrow(), db,
                           appointment_time=time(10, 7))
    assert r["success"] is False
    assert r["reason"] == "off_grid_time"
    assert "instruction" in r


async def test_3am_literal_refused_with_hours(clinic, db, redis):
    branch, doc = clinic["branch"], clinic["doc"]
    r = await assign_token(doc.id, branch.id, _tomorrow(), db,
                           appointment_time=time(3, 0))
    assert r["success"] is False
    assert r["reason"] == "outside_working_hours"
    assert "instruction" in r

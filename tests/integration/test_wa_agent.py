"""The WhatsApp assistant: a short prompt and database tools.

Vinay 2026-08-04, reading a live thread: "Don't complicate WhatsApp prompt.
Just tell it to behave like an appointment booking agent and ask it to answer
everything after confirming from db... Ask it to not answer question outside
appointment flow such as maths, coding, telling jokes etc. also ask it to
behave friendly and warm."

The model is stubbed here — these tests are about the TOOLS, which is where
every fact comes from. Whether the prose is warm is a judgement only a real
thread can settle; whether "book" actually writes a row, whether one patient
can touch another's booking, and whether a cancelled seat is freed are not.
"""
import uuid
from datetime import date, time, timedelta

import pytest
from sqlalchemy import select

from backend.models.schema import (
    Branch, ClinicQuestion, Doctor, DoctorUnavailability, Organization, Token,
)
from backend.services import wa_agent, wa_booking, wa_service


async def _clinic(db):
    org = Organization(
        name="AgentOrg", owner_phone="+919000700055",
        owner_email=f"agent-{uuid.uuid4().hex[:6]}@test.com",
        plan="clinic", status="active",
    )
    db.add(org)
    await db.flush()
    br = Branch(
        org_id=org.id, name="Agent Clinic", status="active",
        timezone="Asia/Kolkata", address="12 Main Rd, Hyderabad",
        whatsapp_number=f"+9199{str(uuid.uuid4().int)[:8]}",
        wa_phone_number_id="pnid-agent",
    )
    db.add(br)
    await db.commit()
    return org, br


async def _doctor(db, branch, name="Srinivas"):
    doc = Doctor(
        branch_id=branch.id, name=name, specialization="dental", status="active",
        booking_type="appointment", slot_duration_minutes=15,
        max_concurrent_per_slot=1, daily_token_limit=20,
        schedule_mode="recurring",
        recurring_schedule={str(d): [{"start": "09:00", "end": "12:00"}] for d in range(7)},
    )
    db.add(doc)
    await db.commit()
    return doc


CALLER = "919876500011"


class StubCalendar:
    """RULE 4 keeps the calendar write inside the booking, so a booking test
    needs one. Same shape as tests/integration/test_wa_booking.py's."""

    def __init__(self):
        self.calls = 0

    async def create_booking_event(self, **kw) -> str:
        self.calls += 1
        return f"evt-{self.calls}"

    async def delete_event(self, calendar_id, event_id) -> None:
        return None


class StubMeta:
    async def send_template(self, *a, **kw):
        return True

    async def send_text(self, *a, **kw):
        return True


def _tools(db, branch, sender=CALLER):
    return wa_agent.WaTools(
        db, branch, sender, "clinic",
        calendar_service=StubCalendar(), meta_service=StubMeta(),
    )


def _tomorrow():
    return (date.today() + timedelta(days=1)).isoformat()


# ── the facts all come from the database ─────────────────────────────────────

@pytest.mark.asyncio
async def test_list_doctors_reads_the_live_roster(db):
    _org, br = await _clinic(db)
    await _doctor(db, br, "Srinivas")
    gone = await _doctor(db, br, "Karishma")
    gone.status = "inactive"
    await db.commit()

    out = await _tools(db, br).list_doctors()
    names = [d["name"] for d in out["doctors"]]
    assert names == ["Srinivas"], "a removed doctor must vanish at once"


@pytest.mark.asyncio
async def test_availability_comes_back_in_am_pm(db):
    """Vinay: "Available from 9 to 13 doesn't look good"."""
    _org, br = await _clinic(db)
    await _doctor(db, br)

    out = await _tools(db, br).check_availability(doctor_name="srinivas", date=_tomorrow())
    assert out["available"] is True
    assert "9 am" in out["free_times"]
    assert not any(":" in t and t.split(":")[0].isdigit() and int(t.split(":")[0]) > 12
                   for t in out["free_times"])


@pytest.mark.asyncio
async def test_a_doctor_on_leave_is_reported_unavailable(db):
    _org, br = await _clinic(db)
    doc = await _doctor(db, br)
    target = date.today() + timedelta(days=1)
    db.add(DoctorUnavailability(
        branch_id=br.id, doctor_id=doc.id, date=target, reason="on leave",
    ))
    await db.commit()

    out = await _tools(db, br).check_availability(
        doctor_name="srinivas", date=target.isoformat()
    )
    assert out["available"] is False


@pytest.mark.asyncio
async def test_an_unknown_doctor_returns_the_real_roster(db):
    _org, br = await _clinic(db)
    await _doctor(db, br)
    out = await _tools(db, br).check_availability(doctor_name="mehta", date=_tomorrow())
    assert out["error"] == "no such doctor"
    assert out["doctors"] == ["Srinivas"]


# ── booking actually writes a row ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_booking_creates_a_confirmed_token(db, redis):
    _org, br = await _clinic(db)
    doc = await _doctor(db, br)

    out = await _tools(db, br).book_appointment(
        doctor_name="srinivas", date=_tomorrow(), time="09:00",
        patient_name="Vinay", patient_age=24,
    )
    assert out["success"] is True, out
    assert out["time"] == "9 am"

    rows = (
        await db.execute(select(Token).where(Token.branch_id == br.id))
    ).scalars().all()
    assert len(rows) == 1 and rows[0].status == "confirmed"
    assert rows[0].doctor_id == doc.id


@pytest.mark.asyncio
async def test_the_same_seat_cannot_be_booked_twice(db, redis):
    """RULE 2. The tool goes through the atomic allocator, not its own maths."""
    _org, br = await _clinic(db)
    await _doctor(db, br)

    first = await _tools(db, br).book_appointment(
        doctor_name="srinivas", date=_tomorrow(), time="09:00",
        patient_name="Vinay", patient_age=24,
    )
    second = await _tools(db, br, sender="919876500022").book_appointment(
        doctor_name="srinivas", date=_tomorrow(), time="09:00",
        patient_name="Other", patient_age=30,
    )
    assert first["success"] is True
    assert second["success"] is False, "double booking is never acceptable"


# ── cancel and reschedule ────────────────────────────────────────────────────

async def _book(db, br):
    out = await _tools(db, br).book_appointment(
        doctor_name="srinivas", date=_tomorrow(), time="09:00",
        patient_name="Vinay", patient_age=24,
    )
    assert out["success"] is True, out
    mine = await _tools(db, br).my_appointments()
    return mine["appointments"][0]["appointment_id"]


@pytest.mark.asyncio
async def test_my_appointments_lists_only_my_own(db, redis):
    _org, br = await _clinic(db)
    await _doctor(db, br)
    await _book(db, br)

    theirs = await _tools(db, br, sender="919876500099").my_appointments()
    assert theirs["appointments"] == [], "RULE 1: another number sees nothing"


@pytest.mark.asyncio
async def test_cancelling_frees_the_seat_for_someone_else(db, redis):
    _org, br = await _clinic(db)
    await _doctor(db, br)
    appt = await _book(db, br)

    assert (await _tools(db, br).cancel_appointment(appointment_id=appt))["success"] is True

    # The whole point of releasing the hold: the slot is bookable again.
    retaken = await _tools(db, br, sender="919876500022").book_appointment(
        doctor_name="srinivas", date=_tomorrow(), time="09:00",
        patient_name="Other", patient_age=30,
    )
    assert retaken["success"] is True, "a cancelled seat must not stay blocked"


@pytest.mark.asyncio
async def test_i_cannot_cancel_someone_elses_booking(db, redis):
    _org, br = await _clinic(db)
    await _doctor(db, br)
    appt = await _book(db, br)

    out = await _tools(db, br, sender="919876500099").cancel_appointment(
        appointment_id=appt
    )
    assert out["success"] is False
    still = (await db.execute(select(Token).where(Token.id == uuid.UUID(appt)))).scalar_one()
    assert still.status == "confirmed"


@pytest.mark.asyncio
async def test_rescheduling_moves_the_booking(db, redis):
    _org, br = await _clinic(db)
    await _doctor(db, br)
    appt = await _book(db, br)

    out = await _tools(db, br).reschedule_appointment(
        appointment_id=appt, date=_tomorrow(), time="09:30",
    )
    assert out["success"] is True, out

    mine = await _tools(db, br).my_appointments()
    assert len(mine["appointments"]) == 1
    assert mine["appointments"][0]["time"] == "9:30 am"


@pytest.mark.asyncio
async def test_a_failed_reschedule_leaves_the_original_intact(db, redis):
    """Take the new seat BEFORE releasing the old, or a patient who asked to
    move an appointment ends up with none at all."""
    _org, br = await _clinic(db)
    await _doctor(db, br)
    appt = await _book(db, br)

    out = await _tools(db, br).reschedule_appointment(
        appointment_id=appt, date=_tomorrow(), time="23:00",  # outside hours
    )
    assert out["success"] is False
    still = (await db.execute(select(Token).where(Token.id == uuid.UUID(appt)))).scalar_one()
    assert still.status == "confirmed", "the original booking must survive"


# ── RULE 7 ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_symptom_question_is_recorded_for_the_doctor(db):
    _org, br = await _clinic(db)
    out = await _tools(db, br).record_question_for_doctor(
        question="my tooth hurts, is it serious?"
    )
    assert out["recorded"] is True
    rows = (
        await db.execute(select(ClinicQuestion).where(ClinicQuestion.branch_id == br.id))
    ).scalars().all()
    assert len(rows) == 1


# ── the prompt says what Vinay asked it to say ───────────────────────────────

def _prompt():
    return wa_agent.SYSTEM_PROMPT.format(
        clinic="Test Clinic", today="2026-08-04", weekday="Tuesday"
    ).lower()


def test_the_prompt_refuses_work_outside_appointments():
    p = _prompt()
    assert "maths" in p and "code" in p


def test_the_prompt_asks_for_warmth():
    p = _prompt()
    assert "warm" in p
    assert "joke" in p


def test_the_prompt_forbids_answering_from_memory():
    """Every fact via a tool — the rule that stops a stale schedule being
    quoted confidently."""
    p = _prompt()
    assert "look it up" in p or "look up" in p
    assert "memory" in p


def test_the_prompt_keeps_the_hard_rules():
    p = _prompt()
    assert "never give medical advice" in p or "never diagnose" in p
    assert "never tell a patient to phone" in p or "no phone line" in p
    assert "9 am" in p and "09:00" in p  # am/pm required, 24-hour named as wrong


def test_no_doctor_facts_are_baked_into_the_prompt():
    """Vinay: "always depend on DB for answering about doctors". The prompt
    carries the clinic name and today's date and nothing else that can drift."""
    p = wa_agent.SYSTEM_PROMPT
    for leak in ("recurring_schedule", "09:00-12:00", "Dr.", "speciality:"):
        assert leak not in p


# ── a promised callback must be a real one ───────────────────────────────────

@pytest.mark.parametrize("reply", [
    "I've made a note for one of our doctors to call you back about it.",
    "I'll have the doctor get back to you.",
    "The doctor will call you shortly.",
])
def test_a_callback_promise_is_detected(reply):
    assert wa_agent._claims_a_callback(reply) is True


@pytest.mark.parametrize("reply", [
    "You're booked with Dr Srinivas on 5 Aug at 9 am. Please be on time.",
    "Srinivas is free 9 am to 12 pm tomorrow.",
    "Hey there! How can I help with your appointments today?",
])
def test_an_ordinary_reply_is_not_mistaken_for_a_promise(reply):
    assert wa_agent._claims_a_callback(reply) is False


@pytest.mark.asyncio
async def test_a_promised_callback_is_recorded_even_when_the_model_forgot(db, monkeypatch):
    """The model repeatedly said "I've made a note for the doctor" while
    calling no tool — a patient waiting for a call nobody would make. Three
    rounds of prompt tightening did not stop it, so the guarantee is enforced
    in code: if the reply promises, the row gets written."""
    _org, br = await _clinic(db)

    class _Resp:
        function_calls = []
        text = "Oh no! I can't say if it's serious, but I've made a note for a doctor to call you back."

    async def fake_model(system, contents, tools):
        return _Resp()

    monkeypatch.setattr(wa_agent, "_call_model", fake_model)
    monkeypatch.setattr(wa_service, "wa_enabled", lambda *a, **k: True)
    sent = []
    async def fake_send(branch, to, text, plan=None):
        sent.append(text)
        return True
    monkeypatch.setattr(wa_service, "send_text", fake_send)

    await wa_agent.handle(db, br, "clinic", CALLER, "my tooth hurts, is it serious?")

    rows = (
        await db.execute(select(ClinicQuestion).where(ClinicQuestion.branch_id == br.id))
    ).scalars().all()
    assert len(rows) == 1, "a promised callback must leave a row the clinic can act on"
    assert "tooth" in rows[0].question
    assert sent, "the patient still gets their reply"

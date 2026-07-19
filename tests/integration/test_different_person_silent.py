"""#295 (live 2026-07-08): when booking for a friend, the agent read the
already_booked instruction and told the patient 'you must say different person'
— internal mechanics leaked into the call. The tool instruction must now direct
the LLM to retry SILENTLY with different_person=true and never voice it. Proof
at the tool layer; the prompt HARD RULES are pinned in test_system_prompt.py."""
import uuid
from datetime import date, time, timedelta

import pytest
import pytest_asyncio

from agent.tools.booking_tools import confirm_booking
from backend.models.schema import Branch, Doctor, Organization, Patient, Token


class _Cal:
    async def create_booking_event(self, **kw):
        return 'evt-1'
    async def delete_event(self, calendar_id, event_id):
        return None


class _Meta:
    async def send_booking_confirmation(self, **kw):
        return None

pytestmark = pytest.mark.asyncio

PHONE = "+919666012345"
# Dynamic: a hardcoded date silently rotted into the past when the calendar
# rolled over (2026-07-10) and the past-date guard fired before the
# different-person path — pin "tomorrow" instead.
BOOK_DATE = date.today() + timedelta(days=1)


@pytest_asyncio.fixture
async def setup(db):
    org = Organization(name="C295", owner_phone="+919000000295",
                       owner_email=f"e295-{uuid.uuid4().hex[:6]}@t.in",
                       plan="clinic", status="active")
    db.add(org); await db.flush()
    br = Branch(org_id=org.id, name="B295",
                whatsapp_number=f"+9111{uuid.uuid4().hex[:8]}", status="active")
    db.add(br); await db.flush()
    doc = Doctor(branch_id=br.id, name="Dr. Lakshmi", specialization="skin",
                 routing_keywords=["skin"], booking_type="appointment",
                 working_hours_start=time(9, 0), working_hours_end=time(17, 0),
                 slot_duration_minutes=30, max_concurrent_per_slot=2, status="active")
    db.add(doc); await db.flush()
    # existing confirmed booking on this phone with this doctor that day
    pat = Patient(branch_id=br.id, name="Caller", phone=PHONE, is_primary=True)
    db.add(pat); await db.flush()
    tok = Token(branch_id=br.id, doctor_id=doc.id, patient_id=pat.id,
                date=BOOK_DATE, status="confirmed", source="voice",
                appointment_time=time(12, 30))
    db.add(tok); await db.flush()
    return br, doc


async def test_different_name_without_flag_stops_before_wrong_attach(setup, db, redis):
    """#421 (real booking 2026-07-19: 'Sudarshan' silently stored under the
    caller 'Vinay'): a clearly different name with different_person=false is
    now caught at patient resolution — BEFORE it can attach to the primary
    record — and the instruction directs a SILENT different_person=true retry
    (#295: never voice the mechanics)."""
    br, doc = setup
    res = await confirm_booking(
        doctor_id=doc.id, branch_id=br.id, patient_name="Prasanna",
        patient_phone=PHONE, complaint="skin", booking_date=BOOK_DATE,
        token_number=1, followup_consent=False, appointment_time=time(12, 30),
        source='voice', calendar_service=_Cal(), meta_service=_Meta(),
        db=db, patient_age=25, different_person=False,
    )
    assert res["success"] is False
    assert res["reason"] == "name_differs_from_phone_owner"
    ins = res["instruction"]
    assert "different_person=true" in ins
    assert "SILENTLY" in ins
    assert "NEVER voice" in ins


async def test_different_person_true_books_through(setup, db, redis):
    """The silent retry actually works: different_person=true books the friend."""
    br, doc = setup
    res = await confirm_booking(
        doctor_id=doc.id, branch_id=br.id, patient_name="Prasanna",
        patient_phone=PHONE, complaint="skin", booking_date=BOOK_DATE,
        token_number=2, followup_consent=False, appointment_time=time(12, 30),
        source='voice', calendar_service=_Cal(), meta_service=_Meta(),
        db=db, patient_age=25, different_person=True,
    )
    assert res["success"] is True


async def test_421_friend_booking_gets_own_patient_record(setup, db, redis):
    """The full #421 repro: 'Sudarshan' booked on Vinay-owned phone must end
    up on a SUDARSHAN patient row, never on the owner's record."""
    from sqlalchemy import select

    br, doc = setup
    res = await confirm_booking(
        doctor_id=doc.id, branch_id=br.id, patient_name="Sudarshan",
        patient_phone=PHONE, complaint="skin",
        booking_date=BOOK_DATE + timedelta(days=1),
        token_number=1, followup_consent=False, appointment_time=time(10, 15),
        source='voice', calendar_service=_Cal(), meta_service=_Meta(),
        db=db, patient_age=30, different_person=False,
    )
    # no-flag call is refused before it can pollute the owner's record...
    assert res["success"] is False and res["reason"] == "name_differs_from_phone_owner"
    res = await confirm_booking(
        doctor_id=doc.id, branch_id=br.id, patient_name="Sudarshan",
        patient_phone=PHONE, complaint="skin",
        booking_date=BOOK_DATE + timedelta(days=1),
        token_number=1, followup_consent=False, appointment_time=time(10, 15),
        source='voice', calendar_service=_Cal(), meta_service=_Meta(),
        db=db, patient_age=30, different_person=True,
    )
    assert res["success"] is True
    # ...and the retry stored it under Sudarshan's OWN row.
    tok = (await db.execute(
        select(Token, Patient).join(Patient, Patient.id == Token.patient_id)
        .where(Token.branch_id == br.id, Token.date == BOOK_DATE + timedelta(days=1))
    )).first()
    assert tok is not None and tok[1].name == "Sudarshan"
    assert tok[1].is_primary is False


def test_names_match_heuristic():
    from agent.tools.booking_tools import _names_match

    # same person, spelling/script variance → match (no question, no split)
    assert _names_match("Vinay", "vinay ")
    assert _names_match("Vinay", "Vinai")          # STT variance, lev 1
    assert _names_match("Vinay Kumar", "Vinay")    # containment
    assert _names_match("Vinay", "వినయ్")           # cross-script → fail-open
    assert _names_match("", "Sudarshan")           # nothing stored → fail-open
    # genuinely different people → mismatch (the #421 corruption)
    assert not _names_match("Vinay", "Sudarshan")
    assert not _names_match("Raju", "Ravi")        # short names stay distinct

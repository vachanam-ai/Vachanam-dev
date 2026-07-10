"""Upfront existing-booking surface in check_availability (FIXLOG #279).

A caller who already has a confirmed booking with a doctor that day should be
told IMMEDIATELY — check_availability(caller_phone=...) returns an
"ALREADY_BOOKED: ..." directive instead of walking the whole flow to discover
it only at confirm_booking. Roast coverage:
  - slot (appointment) doctor → time surfaced
  - token doctor → token number surfaced
  - no caller_phone → old behaviour, never ALREADY_BOOKED (back-compat)
  - different doctor / different date → NOT flagged (no false positive)
  - cancelled / rescheduled-away booking (status != confirmed) → NOT flagged
  - RULE 1: a same-phone booking in ANOTHER branch never leaks in
  - repeated calls stay consistent (idempotent read)
  - family member: caller's number flagged, directive allows continue-if-different
"""
import uuid
from datetime import date, time, timedelta

import pytest
import pytest_asyncio

from agent.tools.booking_tools import check_availability
from backend.models.schema import Branch, Doctor, Organization, Patient, Token

pytestmark = pytest.mark.asyncio

CALLER = "+919666012345"


async def _org_branch(db, tag):
    org = Organization(name=f"C {tag}", owner_phone="+919000000000",
                       owner_email=f"eb-{tag}-{uuid.uuid4().hex[:6]}@t.in",
                       plan="clinic", status="active")
    db.add(org)
    await db.flush()
    br = Branch(org_id=org.id, name=f"B {tag}",
                whatsapp_number=f"+9111{uuid.uuid4().hex[:8]}", status="active")
    db.add(br)
    await db.flush()
    return org, br


async def _slot_doctor(db, branch):
    doc = Doctor(branch_id=branch.id, name="Dr. Slot", specialization="derma",
                 routing_keywords=["skin"], booking_type="appointment",
                 working_hours_start=time(9, 0), working_hours_end=time(17, 0),
                 slot_duration_minutes=30, max_concurrent_per_slot=1, status="active")
    db.add(doc)
    await db.flush()
    return doc


async def _token_doctor(db, branch):
    doc = Doctor(branch_id=branch.id, name="Dr. Queue", specialization="gp",
                 routing_keywords=["fever"], booking_type="token",
                 daily_token_limit=20, status="active")
    db.add(doc)
    await db.flush()
    return doc


async def _seed_confirmed(db, branch, doctor, phone, *, appt_time=None,
                          token_number=None, on=None, status="confirmed"):
    pat = Patient(branch_id=branch.id, name="Caller", phone=phone, is_primary=True)
    db.add(pat)
    await db.flush()
    tok = Token(branch_id=branch.id, doctor_id=doctor.id, patient_id=pat.id,
                date=on or date.today(), status=status, source="voice",
                appointment_time=appt_time, token_number=token_number)
    db.add(tok)
    await db.flush()
    return pat, tok


# --------------------------------------------------------------- positives

async def test_slot_doctor_existing_booking_surfaced_with_time(db, redis):
    _, br = await _org_branch(db, "S1")
    doc = await _slot_doctor(db, br)
    await _seed_confirmed(db, br, doc, CALLER, appt_time=time(11, 0))
    await db.commit()

    out = await check_availability(doc.id, br.id, date.today(), db, caller_phone=CALLER)
    assert out.startswith("ALREADY_BOOKED")
    assert "11:00" in out
    assert doc.name in out


async def test_token_doctor_existing_booking_surfaced_with_number(db, redis):
    _, br = await _org_branch(db, "T1")
    doc = await _token_doctor(db, br)
    await _seed_confirmed(db, br, doc, CALLER, token_number=7)
    await db.commit()

    out = await check_availability(doc.id, br.id, date.today(), db, caller_phone=CALLER)
    assert out.startswith("ALREADY_BOOKED")
    assert "token number 7" in out


# --------------------------------------------------------------- negatives

async def test_no_caller_phone_never_flags(db, redis):
    """Back-compat: existing callers pass no caller_phone → normal availability."""
    _, br = await _org_branch(db, "N1")
    doc = await _token_doctor(db, br)
    await _seed_confirmed(db, br, doc, CALLER, token_number=3)
    await db.commit()

    out = await check_availability(doc.id, br.id, date.today(), db)  # no caller_phone
    assert not out.startswith("ALREADY_BOOKED")


async def test_different_doctor_not_flagged(db, redis):
    _, br = await _org_branch(db, "N2")
    booked_doc = await _token_doctor(db, br)
    other_doc = await _slot_doctor(db, br)
    await _seed_confirmed(db, br, booked_doc, CALLER, token_number=1)
    await db.commit()

    out = await check_availability(other_doc.id, br.id, date.today(), db, caller_phone=CALLER)
    assert not out.startswith("ALREADY_BOOKED")


async def test_different_date_not_flagged(db, redis):
    _, br = await _org_branch(db, "N3")
    doc = await _token_doctor(db, br)
    await _seed_confirmed(db, br, doc, CALLER, token_number=1, on=date.today())
    await db.commit()

    tomorrow = date.today() + timedelta(days=1)
    out = await check_availability(doc.id, br.id, tomorrow, db, caller_phone=CALLER)
    assert not out.startswith("ALREADY_BOOKED")


async def test_cancelled_booking_not_flagged(db, redis):
    """A cancelled/rescheduled-away booking frees the caller to book again."""
    _, br = await _org_branch(db, "N4")
    doc = await _slot_doctor(db, br)
    await _seed_confirmed(db, br, doc, CALLER, appt_time=time(10, 0),
                          status="cancelled_by_patient")
    await db.commit()

    out = await check_availability(doc.id, br.id, date.today(), db, caller_phone=CALLER)
    assert not out.startswith("ALREADY_BOOKED")


async def test_rule1_other_branch_booking_never_leaks(db, redis):
    """RULE 1: same phone booked in branch A must not surface in branch B."""
    _, br_a = await _org_branch(db, "N5A")
    _, br_b = await _org_branch(db, "N5B")
    doc_a = await _token_doctor(db, br_a)
    doc_b = await _token_doctor(db, br_b)
    await _seed_confirmed(db, br_a, doc_a, CALLER, token_number=1)
    await db.commit()

    out = await check_availability(doc_b.id, br_b.id, date.today(), db, caller_phone=CALLER)
    assert not out.startswith("ALREADY_BOOKED")


# --------------------------------------------------------------- robustness

async def test_repeated_calls_stay_consistent(db, redis):
    """Roast: hammering check_availability must return the same verdict."""
    _, br = await _org_branch(db, "R1")
    doc = await _slot_doctor(db, br)
    await _seed_confirmed(db, br, doc, CALLER, appt_time=time(14, 30))
    await db.commit()

    outs = [
        await check_availability(doc.id, br.id, date.today(), db, caller_phone=CALLER)
        for _ in range(5)
    ]
    assert all(o.startswith("ALREADY_BOOKED") and "2:30" in o for o in outs)


async def test_directive_allows_different_person_continue(db, redis):
    """Family booking: caller's number flags, but the directive permits a
    different-person continue (RULE 2 real guard stays in confirm_booking)."""
    _, br = await _org_branch(db, "R2")
    doc = await _slot_doctor(db, br)
    await _seed_confirmed(db, br, doc, CALLER, appt_time=time(9, 30))
    await db.commit()

    out = await check_availability(doc.id, br.id, date.today(), db, caller_phone=CALLER)
    assert "DIFFERENT person" in out


async def test_booking_for_other_suppresses_caller_already_booked(db, redis):
    """#296: caller has a confirmed slot with the doctor that day; booking for a
    FRIEND (booking_for_other) must NOT surface the caller's own ALREADY_BOOKED —
    the helper passes caller_phone=None, so check_availability returns capacity."""
    from agent.livekit_minimal.agent import _availability_caller_phone
    from agent.session_state import SessionState

    org, br = await _org_branch(db, "friend")
    doc = await _slot_doctor(db, br)
    await _seed_confirmed(db, br, doc, CALLER, appt_time=time(15, 0),
                          on=date.today() + timedelta(days=1))
    await db.commit()

    st = SessionState(session_id="friend296")
    st.branch_id = br.id
    st.patient_phone = CALLER
    # normal booking → caller phone flows (would surface ALREADY_BOOKED)
    assert _availability_caller_phone(st) == CALLER
    # friend booking → suppressed
    st.booking_for_other = True
    assert _availability_caller_phone(st) is None

    # and check_availability with caller_phone=None does NOT flag
    res = await check_availability(
        doctor_id=doc.id, branch_id=br.id, booking_date=date.today() + timedelta(days=1),
        db=db, query_start=time(10, 0), query_end=time(11, 0),
        caller_phone=_availability_caller_phone(st),
    )
    assert "ALREADY_BOOKED" not in str(res)

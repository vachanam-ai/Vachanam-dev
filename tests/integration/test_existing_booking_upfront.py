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

from agent.tools.booking_tools import check_availability, find_bookings_by_phone
from backend.models.schema import Branch, Doctor, Organization, Patient, Token

pytestmark = pytest.mark.asyncio

CALLER = "+919666012345"


def _freeze_now(monkeypatch, hh, mm=0, on=None):
    """Pin the branch clock so same-day tests are deterministic at any hour.

    #430 made check_availability ignore appointments that have ALREADY happened
    today, so a suite that seeds "today at 11:00" silently changed meaning
    depending on when it ran (and after 17:00 the test doctor is closed too).
    """
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo as _ZI

    import agent.tools.booking_tools as bt

    fixed = _dt.combine(on or date.today(), time(hh, mm)).replace(
        tzinfo=_ZI("Asia/Kolkata")
    )

    async def _fake_now(branch_id, db):
        return fixed

    monkeypatch.setattr(bt, "_branch_now", _fake_now)
    return fixed


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

async def test_slot_doctor_existing_booking_surfaced_with_time(db, redis, monkeypatch):
    _freeze_now(monkeypatch, 9, 30)          # before the seeded 11:00 (#430)
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

async def test_repeated_calls_stay_consistent(db, redis, monkeypatch):
    """Roast: hammering check_availability must return the same verdict."""
    _freeze_now(monkeypatch, 9, 30)          # before the seeded 14:30 (#430)
    _, br = await _org_branch(db, "R1")
    doc = await _slot_doctor(db, br)
    await _seed_confirmed(db, br, doc, CALLER, appt_time=time(14, 30))
    await db.commit()

    outs = [
        await check_availability(doc.id, br.id, date.today(), db, caller_phone=CALLER)
        for _ in range(5)
    ]
    assert all(o.startswith("ALREADY_BOOKED") and "2:30" in o for o in outs)


async def test_directive_allows_different_person_continue(db, redis, monkeypatch):
    """Family booking: caller's number flags, but the directive permits a
    different-person continue (RULE 2 real guard stays in confirm_booking)."""
    _freeze_now(monkeypatch, 9, 0)           # before the seeded 9:30 (#430)
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


# ------------------------------------------------- #430 false-unavailable bug

async def test_existing_booking_still_reports_live_availability(db, redis, monkeypatch):
    """#430 (Vinay real call 2026-07-20): Dr.Srinivas sat 09:00-23:00 and 7 PM
    was genuinely FREE, but the caller already had a booking that day — the
    upfront surface RETURNED before computing availability and told the model
    'do not run the booking flow', so the agent said "he is not available at
    that time", identically 3/3 times. The note must now ride ALONG WITH the
    real availability, never replace it."""
    _freeze_now(monkeypatch, 9, 30)   # 10:00 booking upcoming, 15:00 bookable
    _, br = await _org_branch(db, "N1")
    doc = await _slot_doctor(db, br)                      # sits 09:00-17:00
    await _seed_confirmed(db, br, doc, CALLER, appt_time=time(10, 0))
    await db.commit()

    out = await check_availability(
        doc.id, br.id, date.today(), db,
        query_start=time(15, 0), query_end=None, caller_phone=CALLER,
    )
    # existing booking still surfaced FIRST (#279 intent preserved)
    assert out.startswith("ALREADY_BOOKED")
    assert "10:00" in out
    # ...but the requested free time is reported as AVAILABLE, not withheld
    assert "3:00 PM" in out
    assert "is available" in out
    # ...and the model is told to move it rather than deny the time
    assert "reschedule_booking" in out
    assert "do NOT say that time is unavailable" in out


async def test_past_same_day_booking_does_not_block(db, redis, monkeypatch):
    """#430 second defect: at 6 PM the tool surfaced a 12:30 PM booking (already
    over) as the reason a later time 'was not available'. An appointment that has
    already happened today cannot block a new one."""
    _freeze_now(monkeypatch, 13, 0)   # 12:30-style "already happened" case
    _, br = await _org_branch(db, "N2")
    doc = await _slot_doctor(db, br)
    # Seeded before the frozen 13:00 -> already happened.
    await _seed_confirmed(db, br, doc, CALLER, appt_time=time(0, 1))
    await db.commit()

    out = await check_availability(doc.id, br.id, date.today(), db, caller_phone=CALLER)
    assert not out.startswith("ALREADY_BOOKED"), out


async def test_upcoming_booking_preferred_over_past_one(db, redis, monkeypatch):
    """When the caller has both a finished and an upcoming appointment today,
    the note must name the UPCOMING one (the 12:30-vs-18:30 mix-up)."""
    _freeze_now(monkeypatch, 13, 0)   # exactly Vinay's 12:30-past / 18:30-next case
    _, br = await _org_branch(db, "N3")
    doc = await _slot_doctor(db, br)
    # ONE patient with TWO tokens (the dedup index forbids a second Patient row
    # for the same branch+phone+name).
    pat, _past = await _seed_confirmed(db, br, doc, CALLER, appt_time=time(0, 1))
    db.add(Token(branch_id=br.id, doctor_id=doc.id, patient_id=pat.id,
                 date=date.today(), status="confirmed", source="voice",
                 appointment_time=time(16, 30)))
    await db.commit()

    out = await check_availability(doc.id, br.id, date.today(), db, caller_phone=CALLER)
    assert out.startswith("ALREADY_BOOKED")
    assert "4:30 PM" in out
    assert "12:01 AM" not in out


async def test_caller_lookup_returns_only_actionable_same_day_slot(db, redis, monkeypatch):
    """The greeting/find/cancel source must never return a finished slot."""
    _freeze_now(monkeypatch, 13, 0)
    _, br = await _org_branch(db, "lookup-now")
    doc = await _slot_doctor(db, br)
    pat, _ = await _seed_confirmed(
        db, br, doc, CALLER, appt_time=time(12, 30)
    )
    future = Token(
        branch_id=br.id, doctor_id=doc.id, patient_id=pat.id,
        date=date.today(), status="confirmed", source="voice",
        appointment_time=time(16, 30),
    )
    db.add(future)
    await db.commit()

    rows = await find_bookings_by_phone(br.id, CALLER, db)
    assert [t.appointment_time for t, _, _ in rows] == [time(16, 30)]

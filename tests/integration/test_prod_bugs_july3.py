"""Regression proofs for the 2026-07-03 prod bugs (voice booking path).

B4: a self-booking must attach to the phone's PRIMARY patient record regardless
    of how STT spelled the name this call — one call hears Telugu "వినయ్", the
    next romanizes "Vinay". Matching on exact name spawned a NEW record per
    spelling, so one caller accumulated 3 records (prod xx7554).

B3: the same caller must not book two DIFFERENT doctors at the SAME time that
    day — a person can't be in two places at once (prod: 16:30 with both
    Dr.Lakshmi and Dr.Srinivas). Family members (different_person) are exempt.
"""
import uuid
from datetime import date, time, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import and_, select

from agent.tools.booking_tools import assign_token, confirm_booking
from backend.models.schema import Branch, Doctor, Organization, Patient, Token

pytestmark = pytest.mark.asyncio


class StubCalendar:
    async def create_booking_event(self, **kw) -> str:
        return "evt"

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
    org = Organization(
        name="J3 Clinic", owner_phone="+919999000033",
        owner_email="j3@clinic.test", plan="clinic", status="active",
    )
    db.add(org)
    await db.flush()
    branch = Branch(
        org_id=org.id, name="J3 Branch", whatsapp_number="+911111000033",
        did_number="+912222000033", emergency_contact="+913333000033", status="active",
    )
    db.add(branch)
    await db.flush()

    def _slot(name, kw):
        return Doctor(
            branch_id=branch.id, name=name, specialization="dermatology",
            routing_keywords=[kw], booking_type="appointment",
            working_hours_start=time(9, 0), working_hours_end=time(18, 0),
            slot_duration_minutes=30, max_concurrent_per_slot=1, status="active",
        )

    lakshmi = _slot("Dr. Lakshmi", "skin")
    srinivas = _slot("Dr. Srinivas", "hair")
    db.add_all([lakshmi, srinivas])
    await db.commit()
    return {"branch": branch, "lakshmi": lakshmi, "srinivas": srinivas}


async def _book(db, branch, doc, name, phone, day, appt, *, different_person=False, age=30):
    assigned = await assign_token(doc.id, branch.id, day, db, appointment_time=appt)
    assert assigned["success"], assigned
    return await confirm_booking(
        doctor_id=doc.id, branch_id=branch.id, patient_name=name, patient_phone=phone,
        complaint="skin", booking_date=day, token_number=assigned["token_number"],
        followup_consent=False, appointment_time=appt, source="voice", db=db,
        calendar_service=StubCalendar(), meta_service=NullMeta(),
        patient_age=age, different_person=different_person,
    )


# ── B4: self-booking reuses the primary record across name spellings ──────────


async def test_b4_self_booking_reuses_primary_across_spellings(clinic, db, redis):
    branch, doc = clinic["branch"], clinic["lakshmi"]
    day = _tomorrow()
    phone = "+919000007554"

    r1 = await _book(db, branch, doc, "వినయ్", phone, day, time(10, 0))
    assert r1["success"], r1
    # SAME person, next call, romanized name, different time → must NOT make a
    # second patient row; reuse the primary.
    r2 = await _book(db, branch, doc, "Vinay", phone, day, time(11, 0))
    # same doctor same day is blocked by the per-doctor guard — that's fine; the
    # point is the PATIENT ROW count. Book the OTHER doctor to avoid that guard:
    r2 = await _book(db, branch, clinic["srinivas"], "Vinay", phone, day, time(11, 0))
    assert r2["success"], r2

    rows = (
        await db.execute(
            select(Patient).where(
                and_(Patient.branch_id == branch.id, Patient.phone == phone)
            )
        )
    ).scalars().all()
    assert len(rows) == 1, f"self-booking spawned duplicate records: {[r.name for r in rows]}"
    assert rows[0].is_primary is True


# ── B3: cross-doctor same-time clash ─────────────────────────────────────────


async def test_b3_same_time_two_doctors_rejected(clinic, db, redis):
    branch = clinic["branch"]
    day = _tomorrow()
    phone = "+919000007555"

    first = await _book(db, branch, clinic["lakshmi"], "వినయ్", phone, day, time(16, 30))
    assert first["success"], first

    # SAME caller (self), SAME time, DIFFERENT doctor → physical impossibility.
    clash = await _book(db, branch, clinic["srinivas"], "వినయ్", phone, day, time(16, 30))
    assert not clash.get("success"), f"cross-doctor time clash was allowed: {clash}"
    assert clash["reason"] == "time_clash"


async def test_r1_already_booked_returns_existing_token_id(clinic, db, redis):
    """already_booked must hand the LLM the BLOCKING booking's token_id so a
    'move my other booking' request is actionable (prod: reminder call only
    knew today's token id and invented 'slot not available')."""
    branch, doc = clinic["branch"], clinic["lakshmi"]
    day = _tomorrow()
    phone = "+919000007557"

    first = await _book(db, branch, doc, "వినయ్", phone, day, time(12, 30))
    assert first["success"], first

    dup = await _book(db, branch, doc, "వినయ్", phone, day, time(15, 0))
    assert not dup.get("success")
    assert dup["reason"] == "already_booked"
    assert dup["existing_token_id"] == str(first["token_id"])
    assert "reschedule_booking" in dup["instruction"]


async def test_b3_family_member_same_time_allowed(clinic, db, redis):
    branch = clinic["branch"]
    day = _tomorrow()
    phone = "+919000007556"

    await _book(db, branch, clinic["lakshmi"], "వినయ్", phone, day, time(16, 30))
    # A genuinely different person on the shared phone CAN be at 16:30 elsewhere.
    fam = await _book(
        db, branch, clinic["srinivas"], "Sita", phone, day, time(16, 30),
        different_person=True,
    )
    assert fam["success"], f"family member wrongly blocked: {fam}"

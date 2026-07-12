"""Regression guards for bug-bounty round 2 (docs/bugbounty/round2.md).

C1 confirm_booking re-checks capacity even when assign_token was skipped.
H1 token counter floored against DB confirmed count after a Redis flush.
M6 same-day past slot refused.
billing_math.call_blocked: expired trial blocks (H5).
telugu_time: spoken time, not digit-by-digit (L6).
"""
from datetime import date, datetime, time, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import and_, func, select

from agent.tools.booking_tools import assign_token, confirm_booking
from backend.models.schema import Branch, Doctor, Organization, Token

pytestmark = pytest.mark.asyncio


class _Cal:
    async def create_booking_event(self, **kw):
        return "evt-r2"

    async def delete_event(self, *a):
        return None


class _Meta:
    async def send_booking_confirmation(self, **kw):
        return None


@pytest_asyncio.fixture
async def clinic(db):
    org = Organization(
        name="R2 Clinic", owner_phone="+919999990022",
        owner_email="r2@clinic.test", plan="clinic", status="active",
    )
    db.add(org)
    await db.flush()
    branch = Branch(
        org_id=org.id, name="R2 Branch", whatsapp_number="+911111110022",
        did_number="+912222220022", status="active",
    )
    db.add(branch)
    await db.flush()
    token_doc = Doctor(
        branch_id=branch.id, name="Dr. Tok", specialization="general_physician",
        routing_keywords=["fever"], is_default_doctor=True, booking_type="token",
        daily_token_limit=3, status="active",
    )
    slot_doc = Doctor(
        branch_id=branch.id, name="Dr. Slot", specialization="dermatology",
        routing_keywords=["skin"], booking_type="appointment",
        working_hours_start=time(9, 0), working_hours_end=time(17, 0),
        slot_duration_minutes=30, max_concurrent_per_slot=1, status="active",
    )
    db.add_all([token_doc, slot_doc])
    await db.commit()
    return {"branch": branch, "token_doc": token_doc, "slot_doc": slot_doc}


def _tomorrow() -> date:
    d = date.today() + timedelta(days=1)
    while d.weekday() == 6:
        d += timedelta(days=1)
    return d


async def _book(db, doc, branch, name, phone, day, appt=None, age=30):
    a = await assign_token(doc.id, branch.id, day, db, appointment_time=appt)
    assert a["success"], a
    return await confirm_booking(
        doctor_id=doc.id, branch_id=branch.id, patient_name=name,
        patient_phone=phone, complaint="x", booking_date=day,
        token_number=a["token_number"], followup_consent=False, patient_age=age,
        appointment_time=appt, source="voice", db=db,
        calendar_service=_Cal(), meta_service=_Meta(),
    )


# ── C1: confirm WITHOUT assign must still honour slot capacity ───────────────


async def test_confirm_without_assign_respects_slot_capacity(clinic, db, redis):
    branch, doc = clinic["branch"], clinic["slot_doc"]
    day = _tomorrow()
    first = await _book(db, doc, branch, "First", "+919666440001", day, appt=time(10, 0))
    assert first["success"]

    # LLM skips assign_token entirely and calls confirm with a made-up token
    # number for the SAME full slot, different person.
    second = await confirm_booking(
        doctor_id=doc.id, branch_id=branch.id, patient_name="Second",
        patient_phone="+919666440002", complaint="x", booking_date=day,
        token_number=99, followup_consent=False, patient_age=40,
        appointment_time=time(10, 0), source="voice", db=db,
        calendar_service=_Cal(), meta_service=_Meta(), different_person=True,
    )
    assert second["success"] is False
    assert second["reason"] == "slot_full"
    confirmed = (
        await db.execute(
            select(func.count()).select_from(Token).where(
                and_(Token.doctor_id == doc.id, Token.date == day,
                     Token.appointment_time == time(10, 0), Token.status == "confirmed")
            )
        )
    ).scalar_one()
    assert confirmed == 1


async def test_confirm_without_assign_respects_token_limit(clinic, db, redis):
    branch, doc = clinic["branch"], clinic["token_doc"]  # daily_token_limit=3
    day = _tomorrow()
    for i in range(3):
        r = await _book(db, doc, branch, f"P{i}", f"+91966644{i:04d}", day)
        assert r["success"], r
    # 4th via confirm-only must be refused (limit reached)
    over = await confirm_booking(
        doctor_id=doc.id, branch_id=branch.id, patient_name="Overflow",
        patient_phone="+919666449999", complaint="x", booking_date=day,
        token_number=2, followup_consent=False, patient_age=30,
        appointment_time=None, source="voice", db=db,
        calendar_service=_Cal(), meta_service=_Meta(), different_person=True,
    )
    assert over["success"] is False
    assert over["reason"] == "full"


# ── H1: token counter survives a Redis flush (no number reuse) ───────────────


async def test_token_counter_floored_after_redis_flush(clinic, db, redis):
    branch, doc = clinic["branch"], clinic["token_doc"]
    day = _tomorrow()
    r1 = await _book(db, doc, branch, "One", "+919666441111", day)
    assert r1["success"]
    # simulate Upstash eviction: wipe the counter key
    await redis.flushdb()
    a2 = await assign_token(doc.id, branch.id, day, db)
    assert a2["success"]
    # must be 2, not a reused 1
    assert a2["token_number"] == 2


# ── M6: same-day past slot refused ──────────────────────────────────────────


async def test_assign_token_refuses_past_slot_today(clinic, db, redis):
    branch, doc = clinic["branch"], clinic["slot_doc"]
    today = date.today()
    # a slot guaranteed in the past today: 09:00 (working hours start) when run
    # any time after 9am; if run before 9am, use a clearly-passed earlier check
    from agent.tools.booking_tools import _branch_now

    now_b = await _branch_now(branch.id, db)
    if now_b.time() <= time(9, 30):
        pytest.skip("test run before clinic opening — no past slot exists today")
    res = await assign_token(doc.id, branch.id, today, db, appointment_time=time(9, 0))
    # refused one way or another — past_slot, outside-hours, or finished-today;
    # the point is a passed same-day 09:00 can NEVER be booked.
    assert res["success"] is False, res


# ── H5: expired trial is blocked even before the pause job runs ──────────────


def test_call_blocked_expired_trial():
    from backend.services.billing_math import call_blocked

    past = datetime.now(timezone.utc) - timedelta(days=1)
    future = datetime.now(timezone.utc) + timedelta(days=3)
    assert call_blocked("trial", "clinic", False, 0, trial_ends_at=past) == "trial_expired"
    assert call_blocked("trial", "clinic", False, 0, trial_ends_at=future) is None
    assert call_blocked("active", "clinic", False, 0, trial_ends_at=past) is None


# ── L6: telugu_time speaks day-part + hour, never raw HH:MM ──────────────────


def test_telugu_time_spoken():
    from agent.services.telugu_dates import telugu_time

    assert telugu_time(time(15, 30)) == "మధ్యాహ్నం మూడున్నర"
    assert "ఉదయం" in telugu_time(time(9, 0))
    assert "సాయంత్రం" in telugu_time(time(17, 0))
    # no ASCII digits leak into the spoken form
    assert not any(c.isdigit() for c in telugu_time(time(16, 30)))


# ── M10/M11/validators: DID normalization ───────────────────────────────────


def test_normalize_did_forms():
    from backend.services.validators import normalize_did

    assert normalize_did("+91 80123 45678") == "+918012345678"
    assert normalize_did("08012345678") == "+918012345678"
    assert normalize_did("918012345678") == "+918012345678"
    assert normalize_did("8012345678") == "+918012345678"

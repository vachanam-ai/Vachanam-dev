"""Task 4: Patient.is_primary is set when a NEW patient row is created.

Rule: the first patient booked on a phone number owns it (is_primary=True).
Family members added later under the same phone are is_primary=False. This is
asserted on the voice-agent booking path (agent.tools.booking_tools.confirm_booking).

Token doctors assign their queue number via atomic Redis INCR (assign_token),
so each booking here first calls assign_token to obtain a real token_number
before confirm_booking persists the row — the same setup the working booking
tests use (tests/integration/test_booking_flow.py).
"""
from datetime import date, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

from agent.tools.booking_tools import assign_token, confirm_booking
from backend.models.schema import Branch, Doctor, Organization, Patient

pytestmark = pytest.mark.asyncio


class StubCalendar:
    """Calendar write MUST succeed for a booking (Rule 4) — stub returns an id."""

    async def create_booking_event(self, **kw) -> str:
        return "evt-stub"

    async def delete_event(self, calendar_id, event_id) -> None:
        return None


class StubMeta:
    """Notification is fire-and-forget — a no-op is fine (Rule 4)."""

    async def send_booking_confirmation(self, **kw):
        return None


def _tomorrow() -> date:
    d = date.today() + timedelta(days=1)
    while d.weekday() == 6:  # skip Sunday (some doctors closed)
        d += timedelta(days=1)
    return d


@pytest_asyncio.fixture
async def clinic(db):
    org = Organization(
        name="Primary Clinic",
        owner_phone="+919999000088",
        owner_email="primary@clinic.test",
        plan="clinic",
        status="active",
    )
    db.add(org)
    await db.flush()
    branch = Branch(
        org_id=org.id,
        name="Primary Branch",
        whatsapp_number="+911111000088",
        did_number="+912222000088",
        emergency_contact="+913333000088",
        status="active",
    )
    db.add(branch)
    await db.flush()
    doc = Doctor(
        branch_id=branch.id,
        name="Dr. Primary",
        specialization="general_physician",
        routing_keywords=["fever"],
        is_default_doctor=True,
        booking_type="token",
        daily_token_limit=50,
        status="active",
    )
    db.add(doc)
    await db.commit()
    return {"branch": branch, "doc": doc}


async def _book(db, branch, doc, name, phone, day, *, different_person=False):
    """Assign a real Redis token, then confirm the booking."""
    assign = await assign_token(doc.id, branch.id, day, db)
    assert assign["success"] is True, assign
    return await confirm_booking(
        doctor_id=doc.id,
        branch_id=branch.id,
        patient_name=name,
        patient_phone=phone,
        complaint="fever",
        booking_date=day,
        token_number=assign["token_number"],
        followup_consent=False,
        appointment_time=None,
        source="voice",
        db=db,
        calendar_service=StubCalendar(),
        meta_service=StubMeta(),
        patient_age=30,
        different_person=different_person,
    )


async def test_first_patient_on_phone_is_primary(clinic, db, redis):
    branch, doc = clinic["branch"], clinic["doc"]
    res = await _book(db, branch, doc, "Ravi", "+919000000010", _tomorrow())
    assert res["success"] is True, res

    p = (
        await db.execute(
            select(Patient).where(
                Patient.phone == "+919000000010", Patient.branch_id == branch.id
            )
        )
    ).scalar_one()
    assert p.is_primary is True


async def test_family_member_is_not_primary(clinic, db, redis):
    branch, doc = clinic["branch"], clinic["doc"]
    day = _tomorrow()

    r1 = await _book(db, branch, doc, "Ravi", "+919000000011", day)
    assert r1["success"] is True, r1
    # A second person on the SAME phone the SAME day: different_person=True lets
    # the family member book past the phone-level duplicate guard.
    r2 = await _book(db, branch, doc, "Sita", "+919000000011", day, different_person=True)
    assert r2["success"] is True, r2

    rows = {
        p.name: p
        for p in (
            await db.execute(
                select(Patient).where(
                    Patient.phone == "+919000000011", Patient.branch_id == branch.id
                )
            )
        ).scalars().all()
    }
    assert rows["Ravi"].is_primary is True
    assert rows["Sita"].is_primary is False

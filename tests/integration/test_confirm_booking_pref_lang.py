"""confirm_booking stamps Patient.preferred_language (Vinay 2026-07-03 case 2).

A caller who switched language BEFORE ever being booked has no patient row for
set_preferred_language to update; the mapping rides SessionState and must be
persisted on the row confirm_booking creates — and applied to an existing row
on a later booking too. Same harness as test_patient_is_primary_on_create.
"""
from datetime import date, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

from agent.tools.booking_tools import assign_token, confirm_booking
from backend.models.schema import Branch, Doctor, Organization, Patient

pytestmark = pytest.mark.asyncio


class StubCalendar:
    async def create_booking_event(self, **kw) -> str:
        return "evt-stub"

    async def delete_event(self, calendar_id, event_id) -> None:
        return None


class StubMeta:
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
        name="PrefLang Clinic",
        owner_phone="+919999000099",
        owner_email="preflang@clinic.test",
        plan="clinic",
        status="active",
    )
    db.add(org)
    await db.flush()
    branch = Branch(
        org_id=org.id,
        name="PrefLang Branch",
        whatsapp_number="+911111000099",
        did_number="+912222000099",
        emergency_contact="+913333000099",
        status="active",
    )
    db.add(branch)
    await db.flush()
    doc = Doctor(
        branch_id=branch.id,
        name="Dr. Lang",
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


async def _book(db, branch, doc, name, phone, day, *, preferred_language=None):
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
        preferred_language=preferred_language,
    )


async def test_new_patient_row_gets_the_mapping(clinic, db, redis):
    branch, doc = clinic["branch"], clinic["doc"]
    res = await _book(db, branch, doc, "Ravi", "+919000000451", _tomorrow(),
                      preferred_language="en")
    assert res["success"] is True, res
    p = (
        await db.execute(
            select(Patient).where(
                Patient.phone == "+919000000451", Patient.branch_id == branch.id
            )
        )
    ).scalar_one()
    assert p.preferred_language == "en"


async def test_existing_row_updated_and_none_leaves_it_alone(clinic, db, redis):
    branch, doc = clinic["branch"], clinic["doc"]
    day = _tomorrow()
    r1 = await _book(db, branch, doc, "Ravi", "+919000000452", day)
    assert r1["success"] is True, r1
    # Second booking (another day) with a switch this call -> row updated.
    r2 = await _book(db, branch, doc, "Ravi", "+919000000452",
                     day + timedelta(days=1), preferred_language="hi")
    assert r2["success"] is True, r2
    p = (
        await db.execute(
            select(Patient).where(
                Patient.phone == "+919000000452", Patient.branch_id == branch.id
            )
        )
    ).scalar_one()
    assert p.preferred_language == "hi"
    # A later booking WITHOUT a switch must not clear the mapping.
    r3 = await _book(db, branch, doc, "Ravi", "+919000000452",
                     day + timedelta(days=2))
    assert r3["success"] is True, r3
    await db.refresh(p)
    assert p.preferred_language == "hi"

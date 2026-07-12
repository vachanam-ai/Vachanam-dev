"""Regression guards for bug-bounty round 3 (docs/bugbounty/round3.md).

T1: the partial unique index makes token-doctor queue numbers race-proof — a
    duplicate (branch,doctor,date,token_number) confirmed row the TOCTOU
    re-count races past is rejected at the DB, surfaced as already_booked.
"""
from datetime import date, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import and_, func, select

from agent.tools.booking_tools import assign_token, confirm_booking
from backend.models.schema import Branch, Doctor, Organization, Token

pytestmark = pytest.mark.asyncio


class _Cal:
    async def create_booking_event(self, **kw):
        return "evt-r3"

    async def delete_event(self, *a):
        return None


class _Meta:
    async def send_booking_confirmation(self, **kw):
        return None


@pytest_asyncio.fixture
async def clinic(db):
    org = Organization(
        name="R3 Clinic", owner_phone="+919999990033",
        owner_email="r3@clinic.test", plan="clinic", status="active",
    )
    db.add(org)
    await db.flush()
    branch = Branch(
        org_id=org.id, name="R3 Branch", whatsapp_number="+911111110033",
        did_number="+912222220033", status="active",
    )
    db.add(branch)
    await db.flush()
    token_doc = Doctor(
        branch_id=branch.id, name="Dr. T3", specialization="general_physician",
        routing_keywords=["fever"], is_default_doctor=True, booking_type="token",
        daily_token_limit=50, status="active",
    )
    db.add(token_doc)
    await db.commit()
    return {"branch": branch, "token_doc": token_doc}


def _tomorrow() -> date:
    d = date.today() + timedelta(days=1)
    while d.weekday() == 6:
        d += timedelta(days=1)
    return d


async def test_duplicate_token_number_rejected_by_unique_index(clinic, db, redis):
    branch, doc = clinic["branch"], clinic["token_doc"]
    day = _tomorrow()
    a = await assign_token(doc.id, branch.id, day, db)
    first = await confirm_booking(
        doctor_id=doc.id, branch_id=branch.id, patient_name="First",
        patient_phone="+919666443301", complaint="fever", booking_date=day,
        token_number=a["token_number"], followup_consent=False, patient_age=30,
        appointment_time=None, source="voice", db=db,
        calendar_service=_Cal(), meta_service=_Meta(),
    )
    assert first["success"], first

    # Force the SAME token_number for a different person — the TOCTOU re-count
    # (limit 50, only 1 booked) would pass; the DB unique index must reject it.
    dup = await confirm_booking(
        doctor_id=doc.id, branch_id=branch.id, patient_name="Second",
        patient_phone="+919666443302", complaint="fever", booking_date=day,
        token_number=a["token_number"], followup_consent=False, patient_age=40,
        appointment_time=None, source="voice", db=db,
        calendar_service=_Cal(), meta_service=_Meta(), different_person=True,
    )
    assert dup["success"] is False
    assert dup["reason"] == "already_booked"

    confirmed = (
        await db.execute(
            select(func.count()).select_from(Token).where(
                and_(Token.doctor_id == doc.id, Token.date == day,
                     Token.token_number == a["token_number"],
                     Token.status == "confirmed")
            )
        )
    ).scalar_one()
    assert confirmed == 1

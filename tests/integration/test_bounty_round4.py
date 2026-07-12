"""Regression guards for bug-bounty round 4 (docs/bugbounty/round4.md).

F2: token-doctor bookings must NOT require a Google Calendar. confirm_booking
    skips the per-patient calendar write for booking_type=="token" (spec §6.5),
    so a token clinic with no calendar configured can still book by voice — the
    most common plan. A raising calendar service must not abort a token booking.

Note: F9 (token capacity should free same-day cancelled seats) is deferred to
TECH_DEBT — a correct fix needs a separate decrement-on-cancel occupancy key so
it never breaks the no-overbook invariant. Not guarded here.
"""
from datetime import date, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import and_, select

from agent.tools.booking_tools import assign_token, confirm_booking
from backend.models.schema import Branch, Doctor, Organization, Token
from backend.services.calendar_service import CalendarNotConfiguredError

pytestmark = pytest.mark.asyncio


class _RaisingCal:
    """Simulates a clinic with no Google Calendar configured."""

    async def create_booking_event(self, **kw):
        raise CalendarNotConfiguredError("no calendar")

    async def delete_event(self, *a):
        return None


class _Meta:
    async def send_booking_confirmation(self, **kw):
        return None


@pytest_asyncio.fixture
async def clinic(db):
    org = Organization(
        name="R4 Clinic", owner_phone="+919999990044",
        owner_email="r4@clinic.test", plan="clinic", status="active",
    )
    db.add(org)
    await db.flush()
    branch = Branch(
        org_id=org.id, name="R4 Branch", whatsapp_number="+911111110044",
        did_number="+912222220044", status="active",
    )
    db.add(branch)
    await db.flush()
    token_doc = Doctor(
        branch_id=branch.id, name="Dr. T4", specialization="general_physician",
        routing_keywords=["fever"], is_default_doctor=True, booking_type="token",
        daily_token_limit=2, status="active",
    )
    db.add(token_doc)
    await db.commit()
    return {"branch": branch, "token_doc": token_doc}


def _tomorrow() -> date:
    d = date.today() + timedelta(days=1)
    while d.weekday() == 6:
        d += timedelta(days=1)
    return d


async def test_token_booking_succeeds_without_calendar(clinic, db, redis):
    """F2: token doctor + no calendar → booking still succeeds, no event id."""
    branch, doc = clinic["branch"], clinic["token_doc"]
    day = _tomorrow()
    a = await assign_token(doc.id, branch.id, day, db)
    res = await confirm_booking(
        doctor_id=doc.id, branch_id=branch.id, patient_name="NoCal",
        patient_phone="+919666443401", complaint="fever", booking_date=day,
        token_number=a["token_number"], followup_consent=False, patient_age=30,
        appointment_time=None, source="voice", db=db,
        calendar_service=_RaisingCal(), meta_service=_Meta(),
    )
    assert res["success"], res
    tok = (
        await db.execute(
            select(Token).where(
                and_(Token.doctor_id == doc.id, Token.date == day,
                     Token.token_number == a["token_number"])
            )
        )
    ).scalar_one()
    assert tok.status == "confirmed"
    assert tok.google_calendar_event_id is None



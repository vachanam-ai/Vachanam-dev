"""iter1 #11 + #19: confirm_booking must not blindly trust the LLM.

Guards proven here (all at the VachanamAgent.confirm_booking tool boundary):
  - patient_phone is not in the tool schema; every booking uses caller-ID.
  - multiple family members can book on one call and share caller-ID.
  - oversized patient_name / complaint and out-of-range patient_age are rejected.
"""
from datetime import date, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

from agent.livekit_minimal.agent import VachanamAgent
from agent.session_state import SessionState
from backend.models.schema import Branch, Doctor, Organization, Patient

pytestmark = pytest.mark.asyncio


class FlakyCalendar:
    async def create_booking_event(self, **kw) -> str:
        return "evt-1"

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
        name="LLMTrust Clinic",
        owner_phone="+919999000077",
        owner_email="llmtrust@clinic.test",
        plan="clinic",
        status="active",
    )
    db.add(org)
    await db.flush()
    branch = Branch(
        org_id=org.id,
        name="LLMTrust Branch",
        whatsapp_number="+911111000022",
        did_number="+912222000033",
        emergency_contact="+913333000044",
        status="active",
    )
    db.add(branch)
    await db.flush()
    doc = Doctor(
        branch_id=branch.id,
        name="Dr. Token",
        specialization="general_physician",
        routing_keywords=["fever"],
        is_default_doctor=True,
        booking_type="token",
        schedule_mode="recurring",
        recurring_schedule={str(i): [{"start": "00:00", "end": "23:59"}] for i in range(7)},
        daily_token_limit=50,
        status="active",
    )
    db.add(doc)
    await db.commit()
    return {"branch": branch, "doc": doc}


def _agent(state, db):
    return VachanamAgent(
        instructions="t",
        state=state,
        db=db,
        room=None,
        calendar_service=FlakyCalendar(),
        meta_service=NullMeta(),
        transfer_to="",
    )


def _state(branch_id):
    s = SessionState(session_id="llmtrust")
    s.branch_id = branch_id
    s.patient_phone = "+919876500011"  # the verified caller-ID
    return s


async def test_phone_override_is_absent_from_tool_schema(clinic, db, redis):
    import inspect

    agent = _agent(_state(clinic["branch"].id), db)
    assert "patient_phone" not in inspect.signature(agent.confirm_booking).parameters


async def test_confirm_sets_existing_booking_intent_for_same_call_change(clinic, db, redis):
    """FIXLOG #284 (Vinay 2026-07-07): after a booking is confirmed the caller
    must be able to change/reschedule it in the SAME call. A confirmed booking
    flips existing_booking_intent so the #279 upfront existing-booking surface no
    longer flags the booking just made (which would dead-end the change)."""
    from agent.livekit_minimal.agent import _availability_caller_phone

    branch, doc = clinic["branch"], clinic["doc"]
    state = _state(branch.id)
    agent = _agent(state, db)
    assert state.existing_booking_intent is False
    # Before booking, a new-booking lookup still surfaces #279 (phone passed).
    assert _availability_caller_phone(state) == state.patient_phone

    r = await agent.confirm_booking(
        context=None,
        doctor_id=str(doc.id),
        patient_name="Selfy",
        complaint="fever",
        booking_date=_tomorrow().isoformat(),
        token_number=1,
        followup_consent=False,
        patient_age=30,
    )
    assert r.get("success"), r
    # After confirming, further "change it" must NOT be blocked by ALREADY_BOOKED.
    assert state.existing_booking_intent is True
    assert _availability_caller_phone(state) is None


async def test_three_family_bookings_share_verified_caller_id(clinic, db, redis):
    branch, doc = clinic["branch"], clinic["doc"]
    state = _state(branch.id)
    agent = _agent(state, db)
    day = _tomorrow().isoformat()

    for i in range(3):
        # fresh hold each booking
        state.token_held = False
        r = await agent.confirm_booking(
            context=None,
            doctor_id=str(doc.id),
            patient_name=f"Family {i}",
            complaint="fever",
            booking_date=day,
            token_number=1,
            followup_consent=False,
            patient_age=20 + i,
            different_person=True,
        )
        assert r.get("success"), r
    patients = (
        await db.execute(select(Patient).where(Patient.branch_id == branch.id))
    ).scalars().all()
    assert {p.name for p in patients} == {"Family 0", "Family 1", "Family 2"}
    assert {p.phone for p in patients} == {state.patient_phone}


async def test_oversized_name_rejected(clinic, db, redis):
    from livekit.agents.llm import ToolError

    branch, doc = clinic["branch"], clinic["doc"]
    agent = _agent(_state(branch.id), db)
    with pytest.raises(ToolError):
        await agent.confirm_booking(
            context=None,
            doctor_id=str(doc.id),
            patient_name="x" * 200,
            complaint="fever",
            booking_date=_tomorrow().isoformat(),
            token_number=1,
            followup_consent=False,
            patient_age=30,
        )


async def test_oversized_complaint_rejected(clinic, db, redis):
    from livekit.agents.llm import ToolError

    branch, doc = clinic["branch"], clinic["doc"]
    agent = _agent(_state(branch.id), db)
    with pytest.raises(ToolError):
        await agent.confirm_booking(
            context=None,
            doctor_id=str(doc.id),
            patient_name="Long Complaint",
            complaint="y" * 600,
            booking_date=_tomorrow().isoformat(),
            token_number=1,
            followup_consent=False,
            patient_age=30,
        )


@pytest.mark.parametrize("bad_age", [-1, 200])
async def test_out_of_range_age_rejected(clinic, db, redis, bad_age):
    from livekit.agents.llm import ToolError

    branch, doc = clinic["branch"], clinic["doc"]
    agent = _agent(_state(branch.id), db)
    with pytest.raises(ToolError):
        await agent.confirm_booking(
            context=None,
            doctor_id=str(doc.id),
            patient_name="Bad Age",
            complaint="fever",
            booking_date=_tomorrow().isoformat(),
            token_number=1,
            followup_consent=False,
            patient_age=bad_age,
        )

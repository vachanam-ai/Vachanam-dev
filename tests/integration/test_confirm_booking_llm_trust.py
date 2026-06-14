"""iter1 #11 + #19: confirm_booking must not blindly trust the LLM.

Guards proven here (all at the VachanamAgent.confirm_booking tool boundary):
  - patient_phone defaults to the VERIFIED caller-ID; an LLM-passed phone is only
    honored when different_person=True.
  - a 3rd different_person (family) booking on one call is refused (cap = 2).
  - oversized patient_name / complaint and out-of-range patient_age are rejected.
"""
from datetime import date, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

from agent.livekit_minimal.agent import VachanamAgent
from agent.session_state import SessionState
from backend.models.schema import Branch, Doctor, Organization, Patient, Token

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


async def test_phone_defaults_to_caller_not_llm_override(clinic, db, redis):
    """#11: a same-person booking ignores an LLM-passed phone and uses caller-ID."""
    branch, doc = clinic["branch"], clinic["doc"]
    state = _state(branch.id)
    agent = _agent(state, db)

    result = await agent.confirm_booking(
        context=None,
        doctor_id=str(doc.id),
        patient_name="Caller Self",
        complaint="fever",
        booking_date=_tomorrow().isoformat(),
        token_number=1,
        followup_consent=False,
        patient_phone="+910000000000",  # LLM-asserted, different_person False
        patient_age=30,
        different_person=False,
    )
    assert result.get("success"), result
    tok = (
        await db.execute(select(Token).where(Token.id == __import__("uuid").UUID(result["token_id"])))
    ).scalar_one()
    patient = (
        await db.execute(select(Patient).where(Patient.id == tok.patient_id))
    ).scalar_one()
    assert patient.phone == "+919876500011", "must attribute to verified caller-ID"
    # the forged LLM phone must NOT have created/used a patient
    assert patient.phone != "+910000000000"


async def test_third_different_person_booking_refused(clinic, db, redis):
    """#11: the 3rd family booking on one call is refused (cap = 2)."""
    from livekit.agents.llm import ToolError

    branch, doc = clinic["branch"], clinic["doc"]
    state = _state(branch.id)
    agent = _agent(state, db)
    day = _tomorrow().isoformat()

    for i in range(2):
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
            patient_phone="+919000000001",
            patient_age=20 + i,
            different_person=True,
        )
        assert r.get("success"), r

    state.token_held = False
    with pytest.raises(ToolError):
        await agent.confirm_booking(
            context=None,
            doctor_id=str(doc.id),
            patient_name="Family 3",
            complaint="fever",
            booking_date=day,
            token_number=1,
            followup_consent=False,
            patient_phone="+919000000001",
            patient_age=40,
            different_person=True,
        )


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

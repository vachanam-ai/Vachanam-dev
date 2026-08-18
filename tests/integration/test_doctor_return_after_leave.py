"""A leave range must lead to the first verified post-leave appointment."""
import uuid
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from agent.livekit_minimal.agent import VachanamAgent
from agent.prompts.grounded_prompt import build_grounded_prompt
from agent.session_state import SessionState
from backend.models.schema import Branch, Doctor, DoctorUnavailability, Organization


@pytest.mark.asyncio
async def test_return_question_offers_first_bookable_day_after_leave(db):
    org = Organization(
        name="Return Clinic",
        owner_phone="+919000700099",
        owner_email=f"return-{uuid.uuid4().hex[:8]}@test.com",
        plan="clinic",
        status="active",
    )
    db.add(org)
    await db.flush()
    branch = Branch(
        org_id=org.id,
        name="Return Branch",
        whatsapp_number=f"+9198{str(uuid.uuid4().int)[:8]}",
        timezone="Asia/Kolkata",
        status="active",
    )
    db.add(branch)
    await db.flush()
    doctor = Doctor(
        branch_id=branch.id,
        name="Dr Lakshmi",
        status="active",
        booking_type="appointment",
        slot_duration_minutes=30,
        max_concurrent_per_slot=1,
        schedule_mode="recurring",
        recurring_schedule={
            str(day): [{"start": "09:00", "end": "12:00"}]
            for day in range(7)
        },
    )
    db.add(doctor)
    await db.flush()

    today = date.today()
    leave_end = today + timedelta(days=4)
    for offset in range(5):
        db.add(DoctorUnavailability(
            branch_id=branch.id,
            doctor_id=doctor.id,
            date=today + timedelta(days=offset),
            reason="leave",
        ))
    await db.commit()

    state = SessionState(session_id="return-after-leave")
    state.branch_id = branch.id
    agent = VachanamAgent(
        instructions="test",
        state=state,
        db=db,
        room=None,
        calendar_service=None,
        meta_service=None,
        transfer_to="",
    )
    result = await VachanamAgent.get_doctor_return_availability.__wrapped__(
        agent, SimpleNamespace(), str(doctor.id)
    )

    expected = leave_end + timedelta(days=1)
    assert result["available"] is True
    assert result["leave_through"] == str(leave_end)
    assert result["date"] == str(expected)
    assert "9:00 AM to 11:30 AM" in result["availability"]
    assert "offer to book" in result["instruction"].lower()

    leave_day = await VachanamAgent.get_doctor_schedule.__wrapped__(
        agent, SimpleNamespace(), str(doctor.id), str(today)
    )
    assert leave_day["available"] is False
    assert leave_day["next_available"]["date"] == str(expected)
    assert "9:00 AM to 11:30 AM" in leave_day["instruction"]


def test_return_after_leave_is_a_required_grounded_tool_call():
    prompt = build_grounded_prompt(
        clinic_name="Test Clinic",
        doctors=[],
        emergency_contact="+919000000000",
        plan="clinic",
        language="en",
    )
    assert "get_doctor_return_availability" in prompt
    assert "Do NOT ask the caller to provide a date" in prompt
    assert "never say \"i don't know\"" in prompt.lower()

"""Caller-ID privacy and automated-agent role locks."""
import inspect
from uuid import uuid4

import pytest
from livekit.agents.llm import ToolError

from agent.livekit_minimal.agent import (
    VachanamAgent,
    _guard_human_booking,
    _looks_like_peer_voice_agent,
    _require_caller_phone,
    _require_verified_identity,
)
from agent.session_state import SessionState


def test_booking_read_and_write_tools_have_no_phone_override():
    assert "patient_phone" not in inspect.signature(VachanamAgent.confirm_booking).parameters
    assert "phone_number" not in inspect.signature(VachanamAgent.find_my_bookings).parameters


def test_verified_sip_caller_number_is_canonicalized():
    assert _require_caller_phone(SessionState(patient_phone="+91 98765-43210")) == (
        "+91 98765-43210",
        "9876543210",
    )
    with pytest.raises(ToolError, match="Caller ID is unavailable"):
        _require_caller_phone(SessionState())


def test_spoofable_ani_cannot_read_or_mutate_until_name_matches():
    state = SessionState(patient_phone="+919876543210")
    with pytest.raises(ToolError, match="exact patient name"):
        _require_verified_identity(state)
    state.identity_verified = True
    state.verified_patient_ids.add(uuid4())
    _require_verified_identity(state)


@pytest.mark.parametrize(
    "speech",
    [
        "Hello, I'm the AI assistant from Clinic A. How can I help you?",
        "నమస్కారం, క్లినిక్ నుంచి AI అసిస్టెంట్‌ని మాట్లాడుతున్నాను. నేను మీకు ఎలా హెల్ప్ చేయగలను?",
        "नमस्ते, मैं क्लिनिक की एआई असिस्टेंट हूँ। मैं आपकी क्या मदद करूँ?",
    ],
)
def test_peer_receptionist_opening_is_detected(speech):
    assert _looks_like_peer_voice_agent(speech)


def test_normal_patient_speech_is_not_peer_agent():
    assert not _looks_like_peer_voice_agent("I need an appointment for my mother")
    assert not _looks_like_peer_voice_agent("Are you an AI assistant?")


def test_peer_agent_cannot_mutate_bookings():
    state = SessionState(peer_agent_detected=True)
    with pytest.raises(ToolError, match="automated clinic assistant"):
        _guard_human_booking(state)


def test_reschedule_and_cancel_queries_require_caller_phone_ownership():
    src = inspect.getsource(VachanamAgent)
    reschedule = src.split("async def _do_reschedule", 1)[1].split(
        "async def cancel_booking", 1
    )[0]
    cancel = src.split("async def _do_cancel", 1)[1]
    assert '_PatientModel.phone.like(f"%{caller_last10}")' in reschedule
    assert 'Patient.phone.like(f"%{caller_last10}")' in cancel

"""Task 2 (2026-07-30 voice-prompt-redesign) — Phase 2 structural grounding
gate. `voice_grounding_gate` defaults OFF: with it off, `_handle_grounded_user_turn`
and `tts_node` behave EXACTLY as before this change. With it on, fee/hours/
booking-status turns are answered from a tool/FAQ result only (think-cue then
proof) instead of being free-formed by the LLM.
"""
from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest
from livekit.agents import StopResponse

from agent.livekit_minimal import agent as agent_module
from agent.livekit_minimal.agent import VachanamAgent
from agent.prompts.system_prompt import DoctorContext
from agent.session_state import SessionState


BRANCH_ID = UUID("2e6d5a8a-30f0-4a90-9a9c-000000000002")


def test_grounding_gate_flag_defaults_off():
    from backend.config import settings

    assert settings.voice_grounding_gate is False


class _RecordingSession:
    def __init__(self):
        self.spoken = []

    def say(self, text, **kwargs):
        self.spoken.append((text, kwargs))


def _message(text):
    return SimpleNamespace(text_content=text, content=text, role="user")


def _agent(state=None, faq=None):
    state = state or SessionState(
        branch_id=BRANCH_ID, branch_timezone="Asia/Kolkata", language="en",
        patient_phone="+919876543210",
    )
    return VachanamAgent(
        instructions="unused by deterministic grounded paths",
        state=state,
        db=object(),
        room=None,
        calendar_service=None,
        meta_service=None,
        transfer_to="",
        lang_code="en",
        doctor_names={},
        doctor_facts=[
            DoctorContext(
                id="1", name="Dr. Ravi", specialization="skin",
                routing_keywords=["skin"], booking_type="appointment",
                is_default=True,
            )
        ],
        faq=faq or [],
    )


def _attach_session(monkeypatch, session):
    monkeypatch.setattr(VachanamAgent, "session", property(lambda _self: session))


@pytest.mark.asyncio
async def test_gate_off_fee_question_is_untouched(monkeypatch):
    """Flag off: fee/hours turns must NOT be intercepted — identical to today
    (falls through to the normal LLM/prefetch path, returns False)."""
    from backend.config import settings

    monkeypatch.setattr(settings, "voice_grounding_gate", False)
    session = _RecordingSession()
    agent = _agent(faq=[{"q": "what is the fee", "a": "The consultation fee is 500 rupees."}])
    _attach_session(monkeypatch, session)

    handled = await agent._handle_grounded_user_turn("what is the doctor's fee")
    assert handled is False
    assert session.spoken == []


@pytest.mark.asyncio
async def test_gate_on_fee_question_answered_from_faq_only(monkeypatch):
    """Gate on: a fee question with a matching FAQ row gets ONE hold-line cue
    then the verbatim FAQ answer — never a free-formed number."""
    from backend.config import settings

    monkeypatch.setattr(settings, "voice_grounding_gate", True)
    session = _RecordingSession()
    agent = _agent(faq=[{"q": "what is the consultation fee", "a": "The consultation fee is 500 rupees."}])
    _attach_session(monkeypatch, session)

    with pytest.raises(StopResponse):
        await agent.on_user_turn_completed(
            SimpleNamespace(items=[]), _message("what is the doctor's fee")
        )

    assert len(session.spoken) == 2
    assert "500 rupees" in session.spoken[1][0]


@pytest.mark.asyncio
async def test_gate_on_hours_question_answered_from_faq_only(monkeypatch):
    from backend.config import settings

    monkeypatch.setattr(settings, "voice_grounding_gate", True)
    session = _RecordingSession()
    agent = _agent(faq=[{"q": "clinic timings", "a": "We are open 9 AM to 8 PM."}])
    _attach_session(monkeypatch, session)

    with pytest.raises(StopResponse):
        await agent.on_user_turn_completed(
            SimpleNamespace(items=[]), _message("what are your clinic hours")
        )

    assert len(session.spoken) == 2
    assert "9 AM to 8 PM" in session.spoken[1][0]


@pytest.mark.asyncio
async def test_gate_on_fee_question_no_faq_match_abstains_and_logs(monkeypatch):
    """No confident FAQ match → abstain with {ask_doctor}, never guess a number."""
    from backend.config import settings

    monkeypatch.setattr(settings, "voice_grounding_gate", True)
    session = _RecordingSession()
    agent = _agent(faq=[{"q": "do you accept insurance", "a": "No, cash only."}])
    _attach_session(monkeypatch, session)
    logged = []

    async def fake_log(_context, question):
        logged.append(question)
        return {"logged": True}

    monkeypatch.setattr(agent, "log_clinic_question", fake_log)

    with pytest.raises(StopResponse):
        await agent.on_user_turn_completed(
            SimpleNamespace(items=[]), _message("what is the fee for consultation")
        )

    assert len(session.spoken) == 2
    assert logged == ["what is the fee for consultation"]
    # Never a number invented in the abstain line.
    assert not any(char.isdigit() for char in session.spoken[1][0])


@pytest.mark.asyncio
async def test_gate_on_booking_status_question_answered_from_db_only(monkeypatch):
    from backend.config import settings

    monkeypatch.setattr(settings, "voice_grounding_gate", True)
    session = _RecordingSession()
    agent = _agent()
    _attach_session(monkeypatch, session)

    async def fake_queue_position_by_phone(_branch_id, _phone, _db):
        return {
            "found": True,
            "queue": [{"token_number": 8, "now_serving": 5, "patients_ahead": 2}],
        }

    async def fake_run_db_read(fn):
        return await fn(object())

    monkeypatch.setattr(agent_module, "queue_position_by_phone", fake_queue_position_by_phone)
    monkeypatch.setattr(agent_module, "run_db_read", fake_run_db_read)

    with pytest.raises(StopResponse):
        await agent.on_user_turn_completed(
            SimpleNamespace(items=[]), _message("which token number is running now")
        )

    assert len(session.spoken) == 2
    assert "5" in session.spoken[1][0] and "2" in session.spoken[1][0]


@pytest.mark.asyncio
async def test_gate_on_booking_status_no_booking_falls_through(monkeypatch):
    """No booking found for this caller → NOT an abstain (that would wrongly
    log a 'clinic question' for an empty queue lookup) — falls through so the
    ordinary get_queue_status tool/LLM path (which already handles this
    correctly) still runs."""
    from backend.config import settings

    monkeypatch.setattr(settings, "voice_grounding_gate", True)
    session = _RecordingSession()
    agent = _agent()
    _attach_session(monkeypatch, session)

    async def fake_queue_position_by_phone(_branch_id, _phone, _db):
        return {"found": False}

    async def fake_run_db_read(fn):
        return await fn(object())

    monkeypatch.setattr(agent_module, "queue_position_by_phone", fake_queue_position_by_phone)
    monkeypatch.setattr(agent_module, "run_db_read", fake_run_db_read)

    handled = await agent._handle_grounded_user_turn("which token number is running now")
    assert handled is False
    # The hold-line cue is allowed (a read genuinely ran); no fabricated fact.
    assert all("500" not in text and "rupees" not in text for text, _ in session.spoken)


@pytest.mark.asyncio
async def test_gate_on_unrecognized_turn_falls_through_untouched(monkeypatch):
    """A turn that isn't fee/hours/booking-status must return False so the
    ordinary LLM/prefetch path still runs, gate on or not."""
    from backend.config import settings

    monkeypatch.setattr(settings, "voice_grounding_gate", True)
    session = _RecordingSession()
    agent = _agent()
    _attach_session(monkeypatch, session)

    handled = await agent._handle_grounded_user_turn("I have a toothache since yesterday")
    assert handled is False
    assert session.spoken == []


@pytest.mark.asyncio
async def test_gate_on_existing_roster_and_exact_time_branches_unaffected(monkeypatch):
    """The pre-existing roster + corrected-exact-time paths must still take
    priority over the new fee/hours/booking-status branch, gate on or off."""
    from backend.config import settings

    monkeypatch.setattr(settings, "voice_grounding_gate", True)
    session = _RecordingSession()
    agent = _agent()
    _attach_session(monkeypatch, session)

    handled = await agent._handle_grounded_user_turn("what doctors do you have")
    assert handled is True
    assert len(session.spoken) == 1
    assert "Dr. Ravi" in session.spoken[0][0]

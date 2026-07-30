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
from agent.livekit_minimal.grounded_turns import (
    asserts_clock_time,
    clinic_fact_intent,
    match_faq_by_intent,
)
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


# ── Task 2.3: narrow tts_node tripwire backstop ──────────────────────────────


async def _stream(*chunks):
    for chunk in chunks:
        yield chunk


async def _collect(agen):
    return "".join([chunk async for chunk in agen])


@pytest.mark.asyncio
async def test_tripwire_off_flag_always_passes_through(monkeypatch):
    from backend.config import settings

    monkeypatch.setattr(settings, "voice_grounding_gate", False)
    agent = _agent()
    agent._state.availability_tool_ran = False

    out = await _collect(
        agent._grounding_tripwire_stream(_stream("Doctor is free at ", "11:30 today."))
    )
    assert out == "Doctor is free at 11:30 today."
    assert agent._state.availability_recheck_needed is False


@pytest.mark.asyncio
async def test_tripwire_on_with_availability_tool_ran_passes_through_untouched(monkeypatch):
    """The turn-flag set (a real read happened this turn) → untouched, even
    though the text asserts a clock time."""
    from backend.config import settings

    monkeypatch.setattr(settings, "voice_grounding_gate", True)
    agent = _agent()
    agent._state.availability_tool_ran = True

    out = await _collect(
        agent._grounding_tripwire_stream(_stream("Doctor is free at ", "11:30 today."))
    )
    assert out == "Doctor is free at 11:30 today."
    assert agent._state.availability_recheck_needed is False


@pytest.mark.asyncio
async def test_tripwire_blocks_ungrounded_clock_time_and_flags_recheck(monkeypatch):
    """No availability tool ran this turn + the reply asserts a clock time →
    replaced with the hold line, and a recheck-needed flag is set."""
    from backend.config import settings

    monkeypatch.setattr(settings, "voice_grounding_gate", True)
    agent = _agent()
    agent._state.availability_tool_ran = False

    out = await _collect(
        agent._grounding_tripwire_stream(_stream("Doctor is free at ", "11:30 today."))
    )
    assert "11:30" not in out
    assert out == "one minute"  # en LangPack hold_line
    assert agent._state.availability_recheck_needed is True


@pytest.mark.asyncio
async def test_tripwire_passes_ordinary_non_time_reply_untouched(monkeypatch):
    """Gate on, tool did NOT run this turn, but the reply names no clock
    time — conservative default: passes through unchanged (err toward
    passing, per spec)."""
    from backend.config import settings

    monkeypatch.setattr(settings, "voice_grounding_gate", True)
    agent = _agent()
    agent._state.availability_tool_ran = False

    out = await _collect(
        agent._grounding_tripwire_stream(_stream("Thank you for calling, ", "have a nice day."))
    )
    assert out == "Thank you for calling, have a nice day."
    assert agent._state.availability_recheck_needed is False


@pytest.mark.asyncio
async def test_tripwire_detects_a_clock_time_split_across_chunk_boundary(monkeypatch):
    """A pattern split mid-token across two LLM chunks must still be caught."""
    from backend.config import settings

    monkeypatch.setattr(settings, "voice_grounding_gate", True)
    agent = _agent()
    agent._state.availability_tool_ran = False

    out = await _collect(
        agent._grounding_tripwire_stream(_stream("The slot is at 11", ":30 pm exactly."))
    )
    assert "11:30" not in out and "pm" not in out
    assert agent._state.availability_recheck_needed is True


# ── Final-review fixes (2026-07-30): C1 detector, C2/I2 grounded context, I3 ──


def test_asserts_clock_time_does_not_trip_on_ordinary_speech():
    """C1: the detector must NOT fire on common receptionist lines. The old
    substring branch matched 'am'⊂'name' and 'one'⊂'phone' — regression-locked."""
    for line in [
        "Can I have your name and phone number?",
        "What is your name and phone?",
        "that costs five hundred rupees",
        "okay, booking for eleven thirty tomorrow morning",  # spelled-out: under-trip is safe
        "your token number is eight",
    ]:
        assert asserts_clock_time(line) is False, line


def test_asserts_clock_time_still_catches_real_clock_times():
    for line in ["the slot is 11:30", "9 am works", "at 5 pm", "3:45 pm"]:
        assert asserts_clock_time(line) is True, line


@pytest.mark.asyncio
async def test_hours_faq_answer_is_not_swallowed_by_tripwire(monkeypatch):
    """C2: an hours answer ("9 AM to 8 PM") trips asserts_clock_time, so the
    fact-turn must mark the turn grounded — otherwise the tripwire eats the
    agent's own hours answer. Assert the grounded context is established."""
    from backend.config import settings

    monkeypatch.setattr(settings, "voice_grounding_gate", True)
    session = _RecordingSession()
    agent = _agent(faq=[{"q": "clinic timings", "a": "We are open 9 AM to 8 PM."}])
    _attach_session(monkeypatch, session)

    with pytest.raises(StopResponse):
        await agent.on_user_turn_completed(
            SimpleNamespace(items=[]), _message("what are your clinic hours")
        )
    assert agent._has_grounded_time_context() is True
    # the hours answer, streamed through the tripwire now, survives
    out = await _collect(agent._grounding_tripwire_stream(_stream("We are open 9 AM to 8 PM.")))
    assert out == "We are open 9 AM to 8 PM."


@pytest.mark.asyncio
async def test_restated_time_passes_once_availability_was_checked(monkeypatch):
    """I2: after a real availability check (last_availability_query_time set),
    the LLM restating that time during name/age collection must pass, not be
    swallowed — even though no tool ran on THIS turn."""
    from backend.config import settings
    from datetime import time

    monkeypatch.setattr(settings, "voice_grounding_gate", True)
    agent = _agent()
    agent._state.availability_tool_ran = False
    agent._state.last_availability_query_time = time(11, 30)

    out = await _collect(
        agent._grounding_tripwire_stream(_stream("so, 11:30 with Dr Ravi — your name?"))
    )
    assert "11:30" in out
    assert agent._state.availability_recheck_needed is False


def test_how_much_time_is_not_a_fee_intent():
    """I3: a duration question must not be classified as fee (and answered from
    a duration FAQ as if it were a price)."""
    assert clinic_fact_intent("how much time will it take") is None
    assert clinic_fact_intent("what is the consultation fee") == "fee"
    assert clinic_fact_intent("how much does it cost") == "fee"
    # a duration FAQ is never returned as the fee answer
    duration_faq = [{"q": "how much time for a filling", "a": "about 45 minutes"}]
    assert match_faq_by_intent("fee", duration_faq) is None


@pytest.mark.asyncio
async def test_slot_confirmation_survives_tripwire(monkeypatch):
    """Regression (inline review, 2026-07-30): a deterministic slot booking /
    reschedule confirmation restates a clock time ("...booked for 11:30 AM"),
    but the confirm turn runs confirm_booking — NOT _read_availability — so
    nothing else marks the turn grounded. Without the confirm path setting the
    flag, the tts_node tripwire (gate on) swallows the confirmation and the
    caller hears "one minute" after a successful booking. The confirm chokepoint
    must mark the turn grounded so the real confirmation passes untouched."""
    from datetime import date, time
    from backend.config import settings

    monkeypatch.setattr(settings, "voice_grounding_gate", True)
    monkeypatch.setattr(settings, "voice_deterministic_confirm", True)
    session = _RecordingSession()
    monkeypatch.setattr(agent_module, "AgentSession", _RecordingSession)
    agent = _agent()
    agent._state.availability_tool_ran = False
    context = SimpleNamespace(session=session)

    spoke = agent._speak_deterministic_confirm(
        context, "booked_slot", token=8, date_=date(2026, 8, 1), time_=time(11, 30),
    )
    assert spoke is True
    confirm_text = session.spoken[0][0]
    assert "11:30" in confirm_text  # the confirm really does assert a clock time
    # The fix: the confirm marks THIS turn grounded...
    assert agent._state.availability_tool_ran is True
    # ...so the same confirmation streams through the tripwire untouched
    # instead of being replaced by the hold line.
    out = await _collect(agent._grounding_tripwire_stream(_stream(confirm_text)))
    assert out == confirm_text
    assert agent._state.availability_recheck_needed is False

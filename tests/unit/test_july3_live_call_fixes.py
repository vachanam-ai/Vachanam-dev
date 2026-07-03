"""Fixes from Vinay's 2026-07-03 live test of family booking + language switch.

Evidence: prod token 16:32Z booked on the CALLER's number after a different
number was dictated (different_person=false discarded the override silently);
Fly log 16:42:29Z 'ToolError ... Unknown doctor' in confirm_booking right
after the hi switch (handoff agent had NO chat history); voice changed on
switch; Telugu endings in a Hindi call.
"""
from agent.livekit_minimal.agent import (
    KNOWN_CALLER_BOOKING_EXTRA,
    VachanamAgent,
    _phone_override_error,
)
from agent.prompts.system_prompt import build_system_prompt
from agent.session_state import SessionState

CALLER = "+918096007554"


# ── Fix A: dictated different number + different_person=false must FAIL LOUDLY ──

def test_different_number_without_flag_is_rejected():
    err = _phone_override_error(CALLER, "+919666444428", different_person=False)
    assert err is not None
    assert "different_person=true" in err


def test_same_number_or_flagged_passes():
    # Caller's own number restated -> fine.
    assert _phone_override_error(CALLER, CALLER, False) is None
    # Same last-10 in a different format -> fine.
    assert _phone_override_error(CALLER, "8096007554", False) is None
    # No phone passed -> fine (defaults to caller).
    assert _phone_override_error(CALLER, None, False) is None
    # Family booking with the flag -> the override is honored, no error.
    assert _phone_override_error(CALLER, "+919666444428", True) is None
    # No caller-ID (rare) -> nothing to compare, don't block.
    assert _phone_override_error(None, "+919666444428", False) is None


# ── Fix B: read-back hard gate in the prompt ──

def test_prompt_gates_dictated_numbers_behind_readback():
    p = build_system_prompt(
        clinic_name="Test", doctors=[], emergency_contact="9",
        plan="clinic", language="te",
    )
    assert "HARD GATE" in p
    assert "SAID YES" in p


def test_known_caller_extra_warns_flag_is_mandatory():
    low = KNOWN_CALLER_BOOKING_EXTRA.format(name="Ravi").lower()
    assert "different_person=false the other number is rejected" in low


# ── Fix C: language-switch handoff carries the conversation history ──

def test_vachanam_agent_accepts_chat_ctx():
    from livekit.agents.llm import ChatContext

    cc = ChatContext.empty()
    cc.add_message(role="user", content="naaku appointment kavali")
    agent = VachanamAgent(
        instructions="x",
        state=SessionState(),
        db=None,
        room=None,
        calendar_service=None,
        meta_service=None,
        transfer_to="",
        chat_ctx=cc,
    )
    texts = " ".join(
        str(getattr(m, "content", "")) for m in agent.chat_ctx.items
    )
    assert "appointment kavali" in texts


def test_vachanam_agent_without_chat_ctx_still_constructs():
    agent = VachanamAgent(
        instructions="x",
        state=SessionState(),
        db=None,
        room=None,
        calendar_service=None,
        meta_service=None,
        transfer_to="",
    )
    assert agent is not None

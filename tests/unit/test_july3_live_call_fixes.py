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
    _availability_caller_phone,
)
from agent.prompts.system_prompt import build_system_prompt
from agent.session_state import SessionState

CALLER = "+918096007554"


# ── Caller ID is now the only booking phone ──

def test_confirm_booking_schema_has_no_phone_override():
    import inspect

    assert "patient_phone" not in inspect.signature(VachanamAgent.confirm_booking).parameters


# ── Fix B: read-back hard gate in the prompt ──

def test_prompt_forbids_dictated_booking_numbers():
    p = build_system_prompt(
        clinic_name="Test", doctors=[], emergency_contact="9",
        plan="clinic", language="te",
    )
    assert "Never ask for, accept, read back, or pass another number" in p


def test_known_caller_extra_warns_flag_is_mandatory():
    low = KNOWN_CALLER_BOOKING_EXTRA.format(name="Ravi").lower()
    assert "always uses the verified number this call came from" in low
    assert "never ask for, accept, repeat, or pass another phone number" in low


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


# ── #281: existing-booking surface must NOT fire during reschedule/cancel ──

def test_availability_caller_phone_new_booking_passes_phone():
    """New-booking track: check_availability gets the caller phone so #279 can
    surface an existing appointment."""
    st = SessionState(patient_phone=CALLER)
    assert _availability_caller_phone(st) == CALLER


def test_availability_caller_phone_suppressed_after_find_my_bookings():
    """Live call 2026-07-06: rescheduling a booking, check_availability for the
    new slot flagged the caller's OWN moved booking as ALREADY_BOOKED and the
    reschedule dead-ended. Once existing_booking_intent is set, no phone is
    passed → no false ALREADY_BOOKED."""
    st = SessionState(patient_phone=CALLER, existing_booking_intent=True)
    assert _availability_caller_phone(st) is None


def test_existing_booking_intent_defaults_false():
    assert SessionState().existing_booking_intent is False

"""Booking and reschedule confirmations include the clinic's punctuality ask."""

import inspect

from agent.livekit_minimal.agent import VachanamAgent
from agent.prompts.system_prompt import build_system_prompt
from agent.tools.booking_tools import confirm_booking


def test_booking_tool_requires_come_on_time_message():
    assert "Please come on time." in inspect.getsource(confirm_booking)


def test_reschedule_tool_requires_come_on_time_message():
    assert "Please come on time." in inspect.getsource(VachanamAgent._do_reschedule)


def test_booking_close_is_once_no_take_care_then_offer_help():
    """Vinay live 2026-07-26: the post-booking close said 'టైంకి రండి' TWICE and
    tacked on 'జాగ్రత్తగా ఉండండి' (take-care). Now: come_on_time ONCE, no
    warm_close after a booking, offer help once, decline → short thanks + end_call."""
    prompt = build_system_prompt("Clinic", [], "", "clinic")
    step6 = prompt.split("On success", 1)[1].split("They may reschedule", 1)[0]
    assert 'టైంకి రండి" ONCE' in step6                       # said once, never twice
    assert 'NO "జాగ్రత్తగా ఉండండి అండి." after a booking' in step6  # no take-care
    assert "ఇంకేమైనా కావాలా అండి?" in step6                  # offer help once
    assert "a short thanks" in step6 and "end_call" in step6  # decline → thanks + end
    # The WARM CLOSE rule is scoped to NOT fire after a booking.
    assert "NOT after a booking" in prompt


def test_prompt_says_punctuality_message_only_after_booking_or_reschedule():
    prompt = build_system_prompt("Clinic", [], "", "clinic")
    flow = prompt.split("<flow>", 1)[1].split("</flow>", 1)[0]
    assert 'On success' in flow and 'say "టైంకి రండి" ONCE' in flow
    assert "RESCHEDULE:" in flow and "టైంకి రండి" in flow.split("RESCHEDULE:", 1)[1].split("CANCEL", 1)[0]
    assert "After:" in flow and 'no "టైంకి రండి"' in flow

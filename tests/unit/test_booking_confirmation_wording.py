"""Booking and reschedule confirmations include the clinic's punctuality ask."""

import inspect

from agent.livekit_minimal.agent import VachanamAgent
from agent.prompts.grounded_prompt import PACKS, _booking_steps
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
    step6 = _booking_steps(PACKS['te']).split("On success", 1)[1]
    come_on_time = PACKS['te'].come_on_time
    assert come_on_time in step6
    assert step6.count(come_on_time) == 1
    assert 'జాగ్రత్తగా ఉండండి' not in step6
    assert "ఇంకేమైనా కావాలా అండి?" in step6                  # offer help once
    assert "end_call" in step6
    # The WARM CLOSE rule is scoped to NOT fire after a booking.
    assert "NOT after a booking" in prompt


def test_prompt_says_punctuality_message_only_after_booking_or_reschedule():
    prompt = build_system_prompt("Clinic", [], "", "clinic")
    come_on_time = PACKS['te'].come_on_time
    assert 'success=true' in prompt and come_on_time in prompt
    reschedule = prompt.split("RESCHEDULE:", 1)[1].split("CANCEL:", 1)[0]
    assert come_on_time in reschedule

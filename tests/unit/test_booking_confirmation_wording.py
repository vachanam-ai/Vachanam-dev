"""Booking and reschedule confirmations include the clinic's punctuality ask."""

import inspect

from agent.livekit_minimal.agent import VachanamAgent
from agent.prompts.system_prompt import build_system_prompt
from agent.tools.booking_tools import confirm_booking


def test_booking_tool_requires_come_on_time_message():
    assert "Please come on time." in inspect.getsource(confirm_booking)


def test_reschedule_tool_requires_come_on_time_message():
    assert "Please come on time." in inspect.getsource(VachanamAgent._do_reschedule)


def test_prompt_says_punctuality_message_only_after_booking_or_reschedule():
    prompt = build_system_prompt("Clinic", [], "", "clinic")
    flow = prompt.split("<flow>", 1)[1].split("</flow>", 1)[0]
    assert 'On success' in flow and 'close with "టైంకి రండి"' in flow
    assert "RESCHEDULE:" in flow and 'Then "టైంకి రండి"' in flow
    assert "AFTER:" in flow and 'no "టైంకి రండి"' in flow

"""Bare twelve is noon in appointment speech, without false positives."""
from pathlib import Path
from datetime import time

import pytest

from agent.livekit_minimal.agent import VachanamAgent, _is_bare_noon_request
from backend.services.wa_agent import SYSTEM_PROMPT as WA_SYSTEM_PROMPT


def test_booking_requests_with_bare_twelve_resolve_to_noon():
    for utterance in (
        "Book an appointment around 12",
        "Can I come at twelve for the doctor?",
        "Appointment pannendu ki kavali",
        "Doctor ko barah baje book karo",
        "Is noon available for consultation?",
    ):
        assert _is_bare_noon_request(utterance), utterance
    assert VachanamAgent._parse_time("12") == time(12, 0)


def test_midnight_and_non_time_twelves_are_not_rewritten():
    for utterance in (
        "Book at 12 AM",
        "Do you have a midnight appointment?",
        "My 12 year old needs a doctor",
        "I have token 12",
        "My mobile number starts with 12",
        "The medicine costs 12 rupees",
    ):
        assert not _is_bare_noon_request(utterance), utterance


@pytest.mark.parametrize(
    ('spoken', 'expected'),
    [
        ('7:45', time(19, 45)),
        ('1:05', time(13, 5)),
        ('8:59', time(20, 59)),
        ('9:00', time(9, 0)),
        ('10', time(10, 0)),
        ('11:30', time(11, 30)),
        ('12:00', time(12, 0)),
        ('21:00', time(21, 0)),
        ('7:45 AM', time(7, 45)),
        ('9 PM', time(21, 0)),
    ],
)
def test_unmarked_times_resolve_inside_the_clinic_day(spoken, expected):
    assert VachanamAgent._parse_time(spoken) == expected


def test_grounding_contract_bans_morning_or_afternoon_for_twelve():
    prompt = Path("agent/prompts/grounded_prompt.py").read_text(encoding="utf-8").lower()
    assert "bare 12" in prompt
    assert "never ask \"morning or afternoon 12?\"" in prompt
    assert "never ask am or pm" in prompt
    assert "If the patient omits am/pm, never ask" in WA_SYSTEM_PROMPT

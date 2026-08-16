"""Bare twelve is noon in appointment speech, without false positives."""
from pathlib import Path
from datetime import time

from agent.livekit_minimal.agent import VachanamAgent, _is_bare_noon_request


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


def test_grounding_contract_bans_morning_or_afternoon_for_twelve():
    prompt = Path("agent/prompts/grounded_prompt.py").read_text(encoding="utf-8").lower()
    assert "bare 12" in prompt
    assert "never ask \"morning or afternoon 12?\"" in prompt

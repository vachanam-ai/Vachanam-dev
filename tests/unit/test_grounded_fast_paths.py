"""Unambiguous DB answers bypass the redundant post-tool LLM pass."""
from datetime import date, time
from pathlib import Path

from agent.livekit_minimal.confirm_speech import (
    build_exact_availability_text,
    build_queue_status_text,
)
from agent.livekit_minimal.agent import _exact_availability_matches


def test_exact_availability_is_native_and_contains_verified_values():
    text = build_exact_availability_text(
        "te", date_=date(2026, 7, 30), time_=time(10, 30)
    )
    assert text and "[happily]" in text and "డాక్టర్" in text
    assert "బుక్ చేయనా" not in text
    assert build_exact_availability_text(
        "ta", date_=date(2026, 7, 30), time_=time(10, 30)
    ) is None


def test_queue_fast_path_requires_complete_single_row_values():
    started = build_queue_status_text(
        "en", {"token_number": 8, "now_serving": 5, "patients_ahead": 2}
    )
    waiting = build_queue_status_text(
        "te", {"token_number": 8, "now_serving": None, "patients_ahead": 7}
    )
    assert started and "Token 5" in started and "2 ahead" in started
    assert waiting and "[softly]" in waiting and "8" in waiting
    assert build_queue_status_text("en", {"token_number": 8}) is None


def test_exact_match_never_turns_a_nearby_slot_into_requested_time():
    assert _exact_availability_matches(
        "Ravi is available 10:30 AM to 10:45 AM on 30 July.",
        "Ravi",
        time(10, 30),
    )
    assert not _exact_availability_matches(
        "Ravi is available 10:45 AM to 11:00 AM on 30 July.",
        "Ravi",
        time(10, 37),
    )
    assert _exact_availability_matches(
        "Dr.Srinivas is available 7:00 PM to 7:15 PM on 30 July.",
        "Dr. Srinivas",
        time(19, 0),
    )


def test_agent_fast_paths_are_narrow_grounded_and_reversible():
    src = Path("agent/livekit_minimal/agent.py").read_text(encoding="utf-8")
    availability = src.split("async def check_availability(", 1)[1].split(
        "async def assign_token(", 1
    )[0]
    queue = src.split("async def get_queue_status(", 1)[1].split(
        "async def log_clinic_question(", 1
    )[0]
    helper = src.split("def _speak_grounded_fast_path(", 1)[1][:1200]
    assert "_exact_availability_matches" in availability
    assert "parsed_end is None or parsed_end <= parsed_start" in availability
    assert "len(queue) == 1" in queue
    assert "settings.voice_grounded_fast_paths" in helper
    assert "isinstance(sess, AgentSession)" in helper

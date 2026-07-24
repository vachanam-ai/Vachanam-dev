"""Verified booking outcomes bypass the redundant second LLM pass."""
from datetime import date, time
from pathlib import Path

from agent.i18n.lines import LINES
from agent.livekit_minimal.confirm_speech import build_confirm_text

D = date(2026, 7, 25)
T = time(10, 30)


def test_telugu_booking_and_reschedule_use_punctuality_wording():
    token = build_confirm_text("te", "booked_token", token=13, date_=D)
    slot = build_confirm_text("te", "booked_slot", date_=D, time_=T)
    moved = build_confirm_text("te", "resched_slot", date_=D, time_=T)
    assert token and "13" in token and "టైంకి రండి" in token
    assert slot and "టైంకి రండి" in slot and "13" not in slot
    assert moved and "టైంకి రండి" in moved and "పాతది" in moved


def test_cancel_is_not_happy_and_does_not_say_come_on_time():
    text = build_confirm_text("te", "cancelled")
    assert text and "[softly]" in text
    assert "[happily]" not in text and "టైంకి" not in text


def test_unsupported_template_or_missing_required_value_falls_back():
    assert build_confirm_text("or", "booked_token", token=3, date_=D) is None
    assert build_confirm_text("te", "booked_token", date_=D) is None
    assert build_confirm_text("te", "unknown", token=1) is None


def test_every_defined_template_formats_without_placeholders():
    for lines in LINES.values():
        for field, values in (
            ("confirm_booked_token", {"token": 12, "date": "x"}),
            ("confirm_booked_slot", {"date": "x", "time": "y"}),
            ("confirm_resched_slot", {"date": "x", "time": "y"}),
            ("confirm_resched_token", {"token": 12, "date": "x"}),
            ("confirm_cancelled", {}),
        ):
            template = getattr(lines, field)
            if template:
                assert "{" not in template.format(**values)


def test_agent_wiring_is_success_gated_and_reversible():
    src = Path("agent/livekit_minimal/agent.py").read_text(encoding="utf-8")
    helper = src.split("def _speak_deterministic_confirm", 1)[1][:2200]
    assert "settings.voice_deterministic_confirm" in helper
    assert "isinstance(sess, AgentSession)" in helper
    assert "sanitize_for_tts" in helper
    assert src.count("raise StopResponse()") >= 3


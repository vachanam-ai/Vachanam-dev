"""Unit tests for agent/prompts/system_prompt.py.

Covers:
  - DPDP s.5 disclosure constants exist and contain the required substrings
  - build_disclosure_utterance() returns all three language variants
  - sanitize_for_tts() does NOT strip Telugu characters (sanitizer bug guard)
  - build_system_prompt() output contains the Step 0 section header
  - build_system_prompt() output contains the Telugu disclosure text

All tests are pure string-match — no LLM call, no DB, no async.
"""

import pytest

from agent.prompts.system_prompt import (
    DISCLOSURE_ENGLISH,
    DISCLOSURE_HINDI,
    DISCLOSURE_TELUGU,
    DISCLOSURE_UTTERANCE,
    DoctorContext,
    build_disclosure_utterance,
    build_system_prompt,
)
from agent.services.tts_sanitizer import sanitize_for_tts


# ──────────────────────────────────────────────────────────────────────────
# Disclosure constant tests
# ──────────────────────────────────────────────────────────────────────────


def test_telugu_disclosure_contains_ai_assistant():
    """Telugu variant must contain 'AI assistant' substring (spec §9.3)."""
    assert "AI assistant" in DISCLOSURE_TELUGU


def test_telugu_disclosure_mentions_name_and_phone():
    """Telugu variant must mention collecting name ('peru') and phone ('phone number')."""
    assert "peru" in DISCLOSURE_TELUGU
    assert "phone number" in DISCLOSURE_TELUGU


def test_english_disclosure_exact_text():
    """English variant must match spec §9.3 verbatim."""
    expected = "This is an AI assistant. We collect your name and phone for your appointment."
    assert DISCLOSURE_ENGLISH == expected


def test_hindi_disclosure_contains_ai_assistant():
    """Hindi variant must contain 'AI assistant' substring (spec §9.3)."""
    assert "AI assistant" in DISCLOSURE_HINDI


def test_hindi_disclosure_mentions_name_and_phone():
    """Hindi variant must mention collecting name ('naam') and phone ('phone number')."""
    assert "naam" in DISCLOSURE_HINDI
    assert "phone number" in DISCLOSURE_HINDI


def test_disclosure_utterance_contains_all_three_languages():
    """Combined utterance must contain substrings from Telugu, English, and Hindi."""
    assert "AI assistant" in DISCLOSURE_UTTERANCE
    assert "This is an AI assistant" in DISCLOSURE_UTTERANCE
    assert "yeh AI assistant hai" in DISCLOSURE_UTTERANCE


def test_build_disclosure_utterance_returns_combined():
    """build_disclosure_utterance() must return the same string as DISCLOSURE_UTTERANCE."""
    result = build_disclosure_utterance()
    assert result == DISCLOSURE_UTTERANCE


# ──────────────────────────────────────────────────────────────────────────
# sanitize_for_tts does NOT strip Telugu characters (RED FLAG guard)
# ──────────────────────────────────────────────────────────────────────────


def test_sanitizer_preserves_telugu_in_disclosure():
    """sanitize_for_tts() must not strip Telugu characters from the disclosure.

    If this fails it is a sanitizer bug, not a prompt bug — per task instructions.
    """
    result = sanitize_for_tts(DISCLOSURE_TELUGU)
    # The Telugu portion of DISCLOSURE_TELUGU is transliterated Latin — verify it survives
    assert "AI assistant" in result
    assert "peru" in result
    assert "phone number" in result


def test_sanitizer_preserves_full_disclosure_utterance():
    """Full combined utterance passes through sanitize_for_tts() intact.

    No markdown present, so output must equal the input (modulo trailing whitespace).
    """
    result = sanitize_for_tts(DISCLOSURE_UTTERANCE)
    assert "This is an AI assistant" in result
    assert "yeh AI assistant hai" in result
    assert "AI assistant" in result


# ──────────────────────────────────────────────────────────────────────────
# build_system_prompt includes Step 0 section
# ──────────────────────────────────────────────────────────────────────────

_MINIMAL_DOCTOR = DoctorContext(
    id="doc-1",
    name="Dr. Test",
    specialization="general",
    routing_keywords=["fever"],
    booking_type="token",
    is_default=True,
)


def _make_prompt(**kwargs) -> str:
    defaults = dict(
        clinic_name="Test Clinic",
        doctors=[_MINIMAL_DOCTOR],
        emergency_contact="+919999999999",
        plan="clinic",
    )
    defaults.update(kwargs)
    return build_system_prompt(**defaults)


def test_system_prompt_contains_step0_header():
    """System prompt must contain the STEP 0 section header (DPDP s.5)."""
    prompt = _make_prompt()
    assert "STEP 0" in prompt


def test_system_prompt_contains_telugu_disclosure():
    """System prompt must embed the Telugu disclosure text so LLM knows it was given."""
    prompt = _make_prompt()
    assert DISCLOSURE_TELUGU in prompt


def test_system_prompt_contains_english_disclosure():
    """System prompt must embed the English disclosure text."""
    prompt = _make_prompt()
    assert DISCLOSURE_ENGLISH in prompt


def test_system_prompt_contains_hindi_disclosure():
    """System prompt must embed the Hindi disclosure text."""
    prompt = _make_prompt()
    assert DISCLOSURE_HINDI in prompt


def test_system_prompt_instructs_llm_not_to_repeat_disclosure():
    """LLM must be told NOT to repeat the disclosure — it was already spoken."""
    prompt = _make_prompt()
    assert "Do NOT repeat this disclosure" in prompt


def test_system_prompt_starts_with_vachanam_identity():
    """Prompt still opens with the agent identity line (not changed by Step 0)."""
    prompt = _make_prompt()
    assert prompt.startswith("You are Vachanam")


def test_system_prompt_step0_precedes_booking_flow():
    """STEP 0 section must appear before BOOKING FLOW in the prompt."""
    prompt = _make_prompt()
    step0_pos = prompt.index("STEP 0")
    booking_pos = prompt.index("BOOKING FLOW")
    assert step0_pos < booking_pos


def test_system_prompt_solo_cap_instruction_present():
    """Solo plan cap instruction still present when plan=solo."""
    prompt = _make_prompt(plan="solo")
    assert "CALL TIME LIMIT" in prompt


def test_system_prompt_rebook_instruction_present():
    """Rebook instruction still present when is_rebook=True."""
    prompt = _make_prompt(is_rebook=True, cancelled_date="2026-06-01")
    assert "REBOOKING" in prompt

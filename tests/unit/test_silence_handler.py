"""Unit tests for silence_handler state machine.

Per tester.md: failing tests first, no implementation in test files, negative
tests for every transition. Pure logic — no I/O, no mocks. Fast.
"""
import pytest

from agent.services.silence_handler import (
    Directive,
    GARBLED_PROMPT_LIMIT,
    SilenceMode,
    SilenceState,
    decide_garbled_directive,
    decide_silence_directive,
)


# ──────────────────────────────────────────────────────────────────────────
# DEFAULT MODE — 5s / 7s / 10s
# ──────────────────────────────────────────────────────────────────────────


def test_default_no_action_before_5s():
    s = SilenceState()
    for t in (0.0, 1.0, 3.0, 4.9):
        assert decide_silence_directive(s, t) == Directive.NONE, f"unexpected directive at t={t}"


def test_default_prompt_1_at_5s():
    s = SilenceState()
    assert decide_silence_directive(s, 5.0) == Directive.PROMPT_1
    assert decide_silence_directive(s, 5.5) == Directive.PROMPT_1
    assert decide_silence_directive(s, 6.9) == Directive.PROMPT_1


def test_default_prompt_2_at_7s_after_prompt_1_emitted():
    s = SilenceState()
    s.prompts_emitted = 1  # agent has already fired prompt 1
    assert decide_silence_directive(s, 7.0) == Directive.PROMPT_2
    assert decide_silence_directive(s, 7.5) == Directive.PROMPT_2


def test_default_skips_to_prompt_2_when_past_threshold_even_if_prompt_1_missed():
    """Defensive behavior: if agent's prompt_1 timer somehow missed (e.g., burst of
    user audio reset things and then they went silent past prompt_2 threshold),
    skip straight to PROMPT_2 rather than getting stuck on PROMPT_1 forever.

    Returning PROMPT_2 here covers the patient with the louder second prompt
    instead of the gentle first one — slightly worse UX but never silent-stuck.
    """
    s = SilenceState()
    s.prompts_emitted = 0
    assert decide_silence_directive(s, 7.5) == Directive.PROMPT_2


def test_default_hangup_at_10s():
    s = SilenceState()
    s.prompts_emitted = 2
    assert decide_silence_directive(s, 10.0) == Directive.HANGUP
    assert decide_silence_directive(s, 12.5) == Directive.HANGUP


def test_default_reset_silence_clears_prompts_emitted():
    s = SilenceState()
    s.prompts_emitted = 2
    s.reset_silence()
    assert s.prompts_emitted == 0


# ──────────────────────────────────────────────────────────────────────────
# WAIT_REQUESTED MODE — 15s / 30s / 45s
# ──────────────────────────────────────────────────────────────────────────


def test_wait_mode_no_action_before_15s():
    s = SilenceState()
    s.mark_wait_requested()
    for t in (5.0, 10.0, 14.9):
        assert decide_silence_directive(s, t) == Directive.NONE


def test_wait_mode_prompt_1_at_15s():
    s = SilenceState()
    s.mark_wait_requested()
    assert decide_silence_directive(s, 15.0) == Directive.PROMPT_1


def test_wait_mode_prompt_2_at_30s():
    s = SilenceState()
    s.mark_wait_requested()
    s.prompts_emitted = 1
    assert decide_silence_directive(s, 30.0) == Directive.PROMPT_2


def test_wait_mode_hangup_at_45s():
    s = SilenceState()
    s.mark_wait_requested()
    s.prompts_emitted = 2
    assert decide_silence_directive(s, 45.0) == Directive.HANGUP


def test_wait_mode_clears_to_default_no_emergency():
    s = SilenceState()
    s.mark_wait_requested()
    s.clear_wait()
    assert s.mode == SilenceMode.DEFAULT


def test_wait_mode_clears_to_emergency_if_emergency_was_detected():
    s = SilenceState()
    s.mark_emergency()
    s.mark_wait_requested()
    s.clear_wait()
    assert s.mode == SilenceMode.EMERGENCY


# ──────────────────────────────────────────────────────────────────────────
# EMERGENCY MODE — silence × 2 (10s / 14s / 20s); wait × 2 (30s / 60s / 90s)
# ──────────────────────────────────────────────────────────────────────────


def test_emergency_mode_default_silence_doubled():
    s = SilenceState()
    s.mark_emergency()
    # Was 5s/7s/10s; now 10s/14s/20s
    assert decide_silence_directive(s, 5.0) == Directive.NONE  # no longer triggers
    assert decide_silence_directive(s, 9.9) == Directive.NONE
    assert decide_silence_directive(s, 10.0) == Directive.PROMPT_1
    s.prompts_emitted = 1
    assert decide_silence_directive(s, 14.0) == Directive.PROMPT_2
    s.prompts_emitted = 2
    assert decide_silence_directive(s, 20.0) == Directive.HANGUP


def test_emergency_mode_wait_silence_doubled():
    s = SilenceState()
    s.mark_emergency()
    s.mark_wait_requested()
    # Was 15s/30s/45s; now 30s/60s/90s
    assert decide_silence_directive(s, 15.0) == Directive.NONE
    assert decide_silence_directive(s, 30.0) == Directive.PROMPT_1
    s.prompts_emitted = 1
    assert decide_silence_directive(s, 60.0) == Directive.PROMPT_2
    s.prompts_emitted = 2
    assert decide_silence_directive(s, 90.0) == Directive.HANGUP


def test_emergency_flag_is_sticky():
    """emergency_detected is one-way — cannot be unmarked once set."""
    s = SilenceState()
    s.mark_emergency()
    assert s.emergency_detected is True
    s.reset_silence()  # should not affect emergency flag
    assert s.emergency_detected is True
    s.mark_wait_requested()  # should not affect emergency flag
    assert s.emergency_detected is True


# ──────────────────────────────────────────────────────────────────────────
# GARBLED COUNTER — uniform across all modes (no per-mode override)
# ──────────────────────────────────────────────────────────────────────────


def test_garbled_under_limit_returns_retry():
    s = SilenceState()
    for i in range(1, GARBLED_PROMPT_LIMIT + 1):  # counts 1, 2, 3
        s.garbled_count = i
        assert decide_garbled_directive(s) == Directive.GARBLED_RETRY


def test_garbled_at_4th_returns_hangup():
    s = SilenceState()
    s.garbled_count = 4  # i.e., the 4th failed turn
    assert decide_garbled_directive(s) == Directive.GARBLED_HANGUP


def test_garbled_counter_uniform_in_emergency_mode():
    """Per spec: emergency does NOT extend garbled counter — 4 = hangup always."""
    s = SilenceState()
    s.mark_emergency()
    s.garbled_count = 4
    assert decide_garbled_directive(s) == Directive.GARBLED_HANGUP


def test_garbled_counter_uniform_in_wait_mode():
    s = SilenceState()
    s.mark_wait_requested()
    s.garbled_count = 4
    assert decide_garbled_directive(s) == Directive.GARBLED_HANGUP


def test_reset_garbled_clears_counter():
    s = SilenceState()
    s.garbled_count = 2
    s.reset_garbled()
    assert s.garbled_count == 0


# ──────────────────────────────────────────────────────────────────────────
# COMBINED — emergency + wait + garbled interactions
# ──────────────────────────────────────────────────────────────────────────


def test_emergency_with_wait_uses_emergency_wait_timeouts():
    s = SilenceState()
    s.mark_emergency()
    s.mark_wait_requested()
    # Should use 30s/60s/90s (emergency × wait), not 15s/30s/45s (plain wait)
    assert decide_silence_directive(s, 15.0) == Directive.NONE
    assert decide_silence_directive(s, 30.0) == Directive.PROMPT_1

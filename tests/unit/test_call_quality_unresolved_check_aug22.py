"""Regression proof for the Aug-20 Aroha unresolved-check quality blind spot."""

from agent.livekit_minimal.agent import _inferred_call_failure
from backend.jobs.call_scoring import _apply_deterministic_quality_rules
from backend.services.call_quality_rules import has_unresolved_check


AROHA_REDACTED_TRANSCRIPT = """\
patient: నా పేరు మీద ఏమైనా అపాయింట్‌మెంట్‌లు ఉన్నాయా?
agent: మీ పేరు చెప్తే మీ అపాయింట్‌మెంట్‌లు చెక్ చేయగలను.
patient: నా పేరు [PATIENT].
agent: దొరికిందండి! ఒక నిమిషం అండి, చెక్ చేసి చెప్తాను.
patient: ఏమైనా అపాయింట్‌మెంట్ ఉందా?
agent: హలో, మీరు ఉన్నారా? హలో, లైన్‌లో ఉన్నారా?
patient: చెప్పండి. ఏ టైమ్‌కు ఉంది?
agent: మీ పేరు మీద అపాయింట్‌మెంట్ ఉందండి. దాన్ని చెక్ చేస్తున్నాను, ఒక నిమిషం.
patient: ఏ టైమ్‌కు ఉంది?
agent: హలో? మీరు ఇంకా లైన్‌లో ఉన్నారా అండి?
agent: రేపు మధ్యాహ్నం రెండున్నరకి ఒక అపాయింట్‌మెంట్ ఉందండి.
"""


def test_aug20_check_then_watchdog_is_a_call_failure():
    assert has_unresolved_check(AROHA_REDACTED_TRANSCRIPT)
    assert _inferred_call_failure(AROHA_REDACTED_TRANSCRIPT) == "unresolved_check"


def test_good_llm_verdict_cannot_waive_unresolved_check_failure():
    verdict = _apply_deterministic_quality_rules(
        AROHA_REDACTED_TRANSCRIPT,
        {"score": 4, "tags": ["good"], "summary": "Correct details were provided."},
    )

    assert verdict["score"] == 2
    assert verdict["tags"] == ["slow_or_repetitive"]
    assert "good" not in verdict["tags"]
    assert "line-presence" in verdict["summary"]


def test_repeated_unresolved_check_promise_is_a_failure_without_watchdog():
    transcript = """\
patient: When is my appointment?
agent: Let me check that for you.
patient: Okay.
agent: I'm checking; one moment.
"""
    assert has_unresolved_check(transcript)


def test_call_ending_on_check_promise_is_a_failure():
    transcript = """\
patient: When is my appointment?
agent: Let me check that for you.
"""
    assert has_unresolved_check(transcript)


def test_promptly_answered_check_is_not_flagged():
    transcript = """\
patient: When is my appointment?
agent: Let me check that for you.
patient: Okay.
agent: Your appointment is tomorrow at 5 PM.
agent: Is there anything else I can help with?
"""
    assert not has_unresolved_check(transcript)
    verdict = {"score": 5, "tags": ["good"], "summary": "Clean call."}
    assert _apply_deterministic_quality_rules(transcript, verdict) is verdict

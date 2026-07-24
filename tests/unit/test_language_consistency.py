"""Regression: FIXLOG #270 — live call 2026-07-05: after an English
switch_language handoff the LLM drifted back to Telugu ("mirror them"
directive + Telugu-heavy history) and the Telugu text went through the
ENGLISH TTS pipeline, producing garbled foreign-sounding audio ("suddenly
started speaking Bengali").

The prompt removes language mirroring and applies an ABSOLUTE same-language
output rule. Soniox is multilingual, so the deleted provider-specific script
override is no longer part of the synthesis boundary.
"""
from __future__ import annotations

# ---------------------------------------------------------------- prompt rules

def _prompt(code: str) -> str:
    from agent.prompts.system_prompt import build_system_prompt
    from types import SimpleNamespace

    doctors = [SimpleNamespace(
        name="Dr. Srinivas", specialization="dental",
        routing_keywords=["tooth"], booking_type="appointment", is_default=True,
    )]
    return build_system_prompt(
        clinic_name="Vasavi",
        doctors=doctors,
        emergency_contact="+919999999999",
        plan="clinic",
        language=code,
    )


def test_non_telugu_prompt_has_absolute_output_language_rule_no_mirroring():
    # The live failure was the POST-SWITCH English agent drifting to Telugu.
    for code in ("en", "hi", "ta"):
        prompt = _prompt(code)
        assert "Everything you say is in\nthe ACTIVE LANGUAGE" in prompt
        assert "Never mirror a language you\nweren't switched into" in prompt


def test_telugu_prompt_switches_only_via_tool_never_text_mirroring():
    # REVISED 2026-07-17 (real call: caller asked English; agent SAID "I can
    # speak English" in TEXT without calling switch_language — pipeline stayed
    # Telugu, next reply drifted back, caller had to ask again). The 06-25
    # "MATCH THE CALLER" text-mirroring is gone: te output is Telugu-only and
    # the ONLY language change is the switch_language tool.
    prompt = _prompt("te")
    assert "mirror them" not in prompt
    assert "MATCH THE CALLER" not in prompt
    assert "switch_language(code) at once" in prompt
    assert "caller code-mixing or English words" in prompt


def test_switch_fence_and_no_revert_rule_every_language():
    # Belt for the 2026-07-17 failure, in EVERY language's prompt: the spoken
    # ack without the tool is named FORBIDDEN; a clear ask switches on the
    # FIRST ask; after a switch the call never drifts back.
    for code in ("te", "en", "hi"):
        prompt = _prompt(code)
        # "Words alone switch NOTHING" is unique to the switch fence (the
        # take_message fence shares the FORBIDDEN date marker).
        assert "switch_language(code) at once" in prompt
        assert "AFTER A SWITCH" in prompt
        assert "Mirror the patient's language" not in prompt

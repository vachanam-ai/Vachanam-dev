"""Regression: FIXLOG #270 — live call 2026-07-05: after an English
switch_language handoff the LLM drifted back to Telugu ("mirror them"
directive + Telugu-heavy history) and the Telugu text went through the
ENGLISH TTS pipeline, producing garbled foreign-sounding audio ("suddenly
started speaking Bengali").

Two layers:
1. Prompt: the mirror directive is gone; an ABSOLUTE same-language output
   rule is present in every language's prompt.
2. Synth boundary: _detect_script_lang overrides the TTS language param to
   match the text's dominant Indic script (RULE 8 — wrong-accent speech
   beats alien garble). Latin text never overrides (te calls are code-mixed).
"""
from __future__ import annotations

from agent.livekit_minimal.agent import _detect_script_lang


# ---------------------------------------------------------------- script guard

def test_latin_text_keeps_configured_language():
    assert _detect_script_lang("I can speak English. How can I help?", "en") == "en"


def test_telugu_text_on_english_call_detected_as_te():
    # The exact live-call failure: Telugu apology emitted post-switch.
    assert _detect_script_lang(
        "అయ్యో, టెక్నికల్ సమస్య వల్ల మీ అపాయింట్‌మెంట్ వివరాలు కనిపించట్లేదండి.", "en"
    ) == "te"


def test_code_mixed_telugu_with_english_loanwords_stays_te():
    # Normal te-call output: Telugu script + Latin loanwords — te must win.
    assert _detect_script_lang("మీ appointment టైమ్ 4:30 కి confirm అయింది", "te") == "te"


def test_bengali_script_detected_as_bn():
    assert _detect_script_lang("আপনার অ্যাপয়েন্টমেন্ট নিশ্চিত", "te") == "bn"


def test_devanagari_respects_marathi_session():
    assert _detect_script_lang("आपली अपॉइंटमेंट नक्की झाली", "mr") == "mr"
    assert _detect_script_lang("आपकी अपॉइंटमेंट पक्की हो गई", "te") == "hi"


def test_empty_text_never_crashes():
    assert _detect_script_lang("", "te") == "te"


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
    for code in ("en", "hi", "bn"):
        prompt = _prompt(code)
        assert "OUTPUT LANGUAGE — ABSOLUTE" in prompt
        assert "mirror them" not in prompt


def test_telugu_prompt_switches_only_via_tool_never_text_mirroring():
    # REVISED 2026-07-17 (real call: caller asked English; agent SAID "I can
    # speak English" in TEXT without calling switch_language — pipeline stayed
    # Telugu, next reply drifted back, caller had to ask again). The 06-25
    # "MATCH THE CALLER" text-mirroring is gone: te output is Telugu-only and
    # the ONLY language change is the switch_language tool.
    prompt = _prompt("te")
    assert "mirror them" not in prompt
    assert "MATCH THE CALLER" not in prompt
    assert "switch_language('en')" in prompt
    assert "TENGLISH IS TELUGU" in prompt  # code-mixing must still never switch


def test_switch_fence_and_no_revert_rule_every_language():
    # Belt for the 2026-07-17 failure, in EVERY language's prompt: the spoken
    # ack without the tool is named FORBIDDEN; a clear ask switches on the
    # FIRST ask; after a switch the call never drifts back.
    for code in ("te", "en", "hi"):
        prompt = _prompt(code)
        # "Words alone switch NOTHING" is unique to the switch fence (the
        # take_message fence shares the FORBIDDEN date marker).
        assert "Words alone switch NOTHING" in prompt
        assert "AFTER A SWITCH" in prompt
        assert "Mirror the patient's language" not in prompt

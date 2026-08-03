"""WhatsApp prompt module (WA MVP1 Task 4).

The voice prompt (agent/prompts/grounded_prompt.py, ~900 lines) is speech
machinery: emotion tags, filler-word rules, pacing, "speak the date in
words never digits". None of that belongs in WhatsApp text, where digits
read BETTER than words and there is no interruption to recover from.
This module is written fresh — it must never import from grounded_prompt.
"""
from __future__ import annotations


def test_no_voice_isms_leak_into_the_chat_prompt():
    """The voice prompt is ~900 lines of speech machinery. In text, digits read
    BETTER than words and there is no interruption to recover from."""
    from agent.prompts.whatsapp_prompt import build_chat_prompt

    p = build_chat_prompt(faq="", turns=[], text="hi").lower()
    for voiceism in (
        "[hesitates]", "filler", "pacing", "tts", "pronounce",
        "interrupt", "speak the date in words",
    ):
        assert voiceism not in p, f"voice-ism leaked into chat prompt: {voiceism}"


def test_prompt_bans_the_call_us_escape_hatch():
    from agent.prompts.whatsapp_prompt import build_chat_prompt

    assert "never tell the patient to call" in build_chat_prompt("", [], "book me").lower()


def test_prompt_carries_conversation_history():
    from agent.prompts.whatsapp_prompt import build_chat_prompt

    turns = [
        {"role": "patient", "text": "tomorrow morning"},
        {"role": "bot", "text": "10:30 or 11:00?"},
    ]
    p = build_chat_prompt("", turns, "10:30")
    assert "tomorrow morning" in p and "10:30 or 11:00" in p


def test_intents_are_exactly_the_nine():
    """doctor_info joined the set 2026-08-03. Before it, "is Dr Srinivas
    available" had no intent to land on, fell through to ask_doctor, and
    became a ClinicQuestion + "let me check with the doctor" for a fact the
    clinic had already entered."""
    from agent.prompts.whatsapp_prompt import INTENTS

    assert set(INTENTS) == {
        "greeting", "book", "reschedule", "cancel", "doctor_info", "location",
        "faq", "ask_doctor", "off_topic",
    }


def test_module_does_not_import_the_voice_prompt():
    """Sharing anything between voice and chat prompts guarantees drift
    (plan Task 4, Global Constraints). A prose mention (e.g. explaining why
    NOT to share code) is fine; an actual import is not."""
    import ast
    import inspect

    from agent.prompts import whatsapp_prompt

    tree = ast.parse(inspect.getsource(whatsapp_prompt))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not any("grounded_prompt" in n.name for n in node.names)
        if isinstance(node, ast.ImportFrom):
            assert not (node.module and "grounded_prompt" in node.module)


def test_ask_doctor_vs_off_topic_distinction_is_explicit():
    """ask_doctor = a real clinic question the FAQ can't answer, reaching the
    doctor. off_topic = prompt injection / general-assistant requests,
    politely redirected and NOT logged as a clinic question. This
    distinction must be unmistakable in the prompt text the model sees."""
    from agent.prompts.whatsapp_prompt import build_chat_prompt

    p = build_chat_prompt("", [], "hi").lower()
    assert "ask_doctor" in p and "off_topic" in p
    assert "reaches the doctor" in p or "goes to the doctor" in p
    assert "poem" in p or "ignore your instructions" in p or "prompt injection" in p


def test_no_medical_judgment_rule_present():
    """RULE 7 — a symptom question is ask_doctor, never a diagnosis, advice,
    or urgency/triage assessment."""
    from agent.prompts.whatsapp_prompt import build_chat_prompt

    p = build_chat_prompt("", [], "my tooth hurts, is it serious?").lower()
    assert "no medical" in p or "never diagnose" in p or "never give medical advice" in p
    assert "triage" in p or "urgency" in p


def test_style_rules_present():
    from agent.prompts.whatsapp_prompt import build_chat_prompt

    p = build_chat_prompt("", [], "hi").lower()
    assert "3 sentences" in p or "three sentences" in p
    assert "digit" in p
    assert "emoji" in p
    assert "markdown" in p or "bullet" in p


def test_prompt_includes_the_faq_text():
    from agent.prompts.whatsapp_prompt import build_chat_prompt

    p = build_chat_prompt("Q: hours?\nA: 9-6", [], "hi")
    assert "Q: hours?" in p and "A: 9-6" in p


def test_prompt_includes_the_current_patient_text():
    from agent.prompts.whatsapp_prompt import build_chat_prompt

    p = build_chat_prompt("", [], "book me for tomorrow")
    assert "book me for tomorrow" in p

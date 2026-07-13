"""#368 (Vinay real call 2026-07-14): "Hindi intro is too large and it is
repeating itself. Follow same rules as Telugu. Short intro... across all
languages."

Rule: EVERY language has the trimmed one-sentence inbound_intro (+ the
known-caller variant with {patient}) — greeting.py then returns it as the
SINGLE opening segment, so the "welcome to {clinic}" + disclosure pair (which
said the clinic name twice) can never be spoken again in any language.
"""
from agent.i18n.lines import LINES
from agent.livekit_minimal.greeting import inbound_greeting_texts


def test_every_language_has_short_intros():
    for code, lines in LINES.items():
        assert lines.inbound_intro, code
        assert "{clinic}" in lines.inbound_intro, code
        assert lines.inbound_intro_known, code
        assert "{patient}" in lines.inbound_intro_known, code
        # the intro replaces the welcome line — it must not ALSO say
        # "welcome to the clinic" in any language (that was the repetition)
        for banned in ("స్వాగతం", "स्वागत", "வரவேற்", "ಸ್ವಾಗತ", "സ്വാഗതം",
                       "স্বাগতম", "ସ୍ୱାଗତ", "welcome"):
            assert banned not in lines.inbound_intro.lower(), (code, banned)


def test_inbound_opening_is_one_segment_everywhere():
    for code in LINES:
        unknown = inbound_greeting_texts(code, "TestClinic")
        known = inbound_greeting_texts(code, "TestClinic", spk_caller="Vinay")
        assert len(unknown) == 1, (code, unknown)
        assert len(known) == 1, (code, known)
        assert "Vinay" in known[0], code
        assert "TestClinic" in unknown[0], code


# ── #370: garbled cross-language switch request (Vinay call 2026-07-14) ──────


def test_prompt_handles_garbled_switch_requests():
    """'Hindi mein baat kar sakte' through te-locked STT arrives as Telugu
    word-salad — the prompt must run the confirm-then-switch ladder instead
    of ignoring it."""
    from agent.prompts.system_prompt import build_system_prompt

    p = build_system_prompt(
        clinic_name="C", doctors=[], emergency_contact="+911234567890",
        plan="clinic", language="te", faq=None,
    )
    assert "GARBLED SWITCH REQUEST" in p
    assert "POSSIBLE switch request" in p
    assert "AGAIN in any following turn" in p  # 2nd mention → switch, no loop
    assert "switch, do not keep asking" in p

"""Multilingual voice-agent infra (Vinay 2026-06-15): per-clinic language.

Proves the language seam is correct and SAFE:
  - the registry covers the MVP languages with the right Sarvam codes
  - an unknown/None Branch.language always falls back to Telugu (a bad value can
    never break a live call — RULE 8)
  - every language's spoken lines are present, complete, and in their OWN script
    (no Devanagari-in-Telugu style paste corruption)
  - build_system_prompt leaves Telugu byte-identical (no regression for the live
    clinic) and gives every other language a hard PRIMARY-LANGUAGE directive
"""
import unicodedata as U

import pytest

from agent.i18n import LANGUAGES, get_lang, get_lines
from agent.i18n.lines import Lines
from agent.prompts.system_prompt import DoctorContext, build_system_prompt

EXPECTED = {"te", "en", "hi", "ta", "kn", "ml", "mr", "bn"}  # Odia removed 2026-07-24

# Each internal code -> the Unicode script its letters must belong to.
SCRIPT_OF = {
    "te": "TELUGU", "en": "LATIN", "hi": "DEVANAGARI", "ta": "TAMIL",
    "kn": "KANNADA", "ml": "MALAYALAM", "mr": "DEVANAGARI", "bn": "BENGALI",
}
# Shared Indic punctuation/joiners allowed in any script.
_SHARED = {0x0964, 0x0965, 0x200C, 0x200D}


def test_registry_covers_mvp_languages():
    assert EXPECTED <= set(LANGUAGES)


def test_stt_tts_codes_correct():
    # STT = Sarvam Saaras (*-IN). Soniox TTS uses short language codes.
    assert get_lang("te").stt_code == "te-IN"
    assert get_lang("te").tts_code == "te"
    assert get_lang("te").default_voice == "Priya"
    assert get_lang("bn").stt_code == "bn-IN"
    assert get_lang("hi").default_voice == "Priya"


# "EN" left this list 2026-07-03 — English became a real language (per-caller
# language mapping) and now resolves case-insensitively instead of falling back.
@pytest.mark.parametrize("bad", [None, "", "zz", "FR", "  ", "klingon"])
def test_unknown_language_falls_back_to_telugu(bad):
    assert get_lang(bad).code == "te"
    assert get_lines(bad) is get_lines("te")


def test_language_code_is_case_insensitive():
    assert get_lang("TE").code == "te"
    assert get_lang("Hi").code == "hi"


@pytest.mark.parametrize("code", sorted(EXPECTED))
def test_lines_complete(code):
    lines = get_lines(code)
    assert isinstance(lines, Lines)
    assert len(lines.fillers) >= 3 and all(f.strip() for f in lines.fillers)
    # Greeting placeholders survive for the call site to fill. (disclosure_greeting
    # is a fixed line now — the welcome clip carries the clinic name, 2026-06-24.)
    assert "{patient}" in lines.known_caller_greeting and "{clinic}" in lines.known_caller_greeting
    for ph in ("{patient}", "{clinic}", "{time}", "{doctor}"):
        assert ph in lines.reminder_greeting
    for ph in ("{patient}", "{clinic}", "{date}", "{doctor}"):
        assert ph in lines.rebook_greeting
    assert lines.service_blocked.strip()
    assert lines.cap_warning.strip() and lines.cap_goodbye.strip()


@pytest.mark.parametrize("code", sorted(EXPECTED))
def test_spoken_lines_are_in_their_own_script(code):
    """No paste corruption: every non-ASCII letter must be in the clinic's own
    script (allowing shared danda/joiners and the {placeholders})."""
    lines = get_lines(code)
    spoken = (
        lines.disclosure_greeting + lines.known_caller_greeting
        + lines.reminder_greeting + lines.rebook_greeting
        + lines.service_blocked + lines.cap_warning + lines.cap_goodbye
        + "".join(lines.fillers)
    )
    want = SCRIPT_OF[code]
    offenders = []
    for ch in spoken:
        o = ord(ch)
        if ch.isascii() or ch.isspace() or o in _SHARED or ch in "{}!?.,—-…":
            continue
        try:
            script = U.name(ch).split(" ")[0]
        except ValueError:
            script = "UNNAMED"
        if script != want:
            offenders.append((hex(o), script))
    assert not offenders, f"{code} has non-{want} chars: {offenders[:8]}"


def _docs():
    return [DoctorContext("id1", "Dr Asha", "dentist", ["tooth"], "token", True)]


def test_telugu_prompt_has_no_directive():
    p = build_system_prompt("Clinic", _docs(), "+919999999999", "clinic", language="te")
    assert not p.startswith("PRIMARY LANGUAGE")
    assert "You speak Telugu." in p


@pytest.mark.parametrize("code,name", [("hi", "Hindi"), ("ta", "Tamil"), ("bn", "Bengali")])
def test_non_telugu_prompt_has_primary_language_directive(code, name):
    p = build_system_prompt("Clinic", _docs(), "+919999999999", "clinic", language=code)
    assert p.startswith("PRIMARY LANGUAGE")
    assert f"You speak {name}." in p


def test_unknown_prompt_language_equals_telugu():
    te = build_system_prompt("Clinic", _docs(), "+919999999999", "clinic", language="te")
    zz = build_system_prompt("Clinic", _docs(), "+919999999999", "clinic", language="zz")
    assert zz == te

"""Language switching (Vinay 2026-07-03 case 2): English as a 9th language,
per-caller mapping plumbing, switch directive in the prompt, and the
clone-voice fallback for a switched language."""
from types import SimpleNamespace

from agent.i18n import LANGUAGES, get_lang, get_lines, get_switch_ack, get_welcome
from agent.livekit_minimal.agent import _voice_for_lang
from agent.prompts.system_prompt import build_system_prompt


def test_english_is_a_supported_language():
    assert "en" in LANGUAGES
    cfg = get_lang("en")
    assert cfg.stt_code == "en-IN"       # Sarvam Saaras
    assert cfg.tts_code == "en"          # smallest.ai short code
    lines = get_lines("en")
    # Every spoken line the call paths use must exist in English.
    for field in (
        "service_blocked", "disclosure_greeting", "known_caller_greeting",
        "reminder_greeting", "rebook_greeting", "cap_warning", "cap_goodbye",
        "followup_greeting_q", "followup_greeting_noq",
        "inbound_followup_greeting", "followup_name_prefix",
    ):
        assert getattr(lines, field), f"en Lines.{field} missing"
    assert lines.fillers
    assert "{clinic}" in get_welcome("en")


def test_switch_ack_exists_for_every_language():
    for code in LANGUAGES:
        assert get_switch_ack(code), f"no switch ack for {code}"
    # Unknown code falls back to Telugu, never empty (RULE 8).
    assert get_switch_ack("xx") == get_switch_ack("te")


def test_prompt_carries_switch_directive_in_all_languages():
    for code in ("te", "en", "hi"):
        p = build_system_prompt(
            clinic_name="Test", doctors=[], emergency_contact="9",
            plan="clinic", language=code,
        )
        assert "switch_language" in p
        # Explicit-ask only — never speech auto-detect (2026-06-17 decision).
        assert "EXPLICITLY" in p
        assert "NEVER because" in p
        # Live test 2026-07-03: the LLM spoke its own ack alongside the tool
        # call (double-voice) — the switch turn must be silent.
        assert "SILENTLY" in p


def test_solo_cap_copy_says_ten_minutes():
    """Vinay 2026-07-03: solo per-call cap raised 4 -> 10 minutes."""
    p = build_system_prompt(
        clinic_name="Test", doctors=[], emergency_contact="9",
        plan="solo", language="te",
    )
    assert "10 minutes" in p
    assert "4 minutes" not in p


def _branch(voice, clones):
    return SimpleNamespace(tts_voice=voice, cloned_voices=clones)


def test_voice_for_lang_keeps_catalog_voice():
    b = _branch("padmaja", [])
    assert _voice_for_lang(b, "en") == "padmaja"


def test_voice_for_lang_clone_is_language_bound():
    """Measured 2026-07-03 (smallest live API): a te clone speaking en returned
    0.45s of noise for a full sentence — gibberish on a real call. A clone may
    ONLY voice its registered language; other languages use that language's
    default catalog voice."""
    b = _branch("clone123", [{"voice_id": "clone123", "name": "Sree", "language": "te"}])
    assert _voice_for_lang(b, "te") == "clone123"
    assert _voice_for_lang(b, "en") == get_lang("en").default_voice
    assert _voice_for_lang(b, "hi") == get_lang("hi").default_voice


def test_voice_for_lang_no_voice_set_uses_language_default():
    b = _branch(None, [])
    assert _voice_for_lang(b, "hi") == get_lang("hi").default_voice


def test_voice_for_lang_per_language_clone_wins():
    """FIXLOG #265 (Vinay 2026-07-05): the agent speaks ONLY clinic voices —
    the clone registered for the CALL's language always wins, even when the
    branch's tts_voice is a catalog voice or another language's clone."""
    b = _branch("padmaja", [
        {"voice_id": "clone_te", "name": "Sree", "language": "te"},
        {"voice_id": "clone_hi", "name": "Sree-hi", "language": "hi"},
    ])
    assert _voice_for_lang(b, "te") == "clone_te"
    assert _voice_for_lang(b, "hi") == "clone_hi"   # switch inherits clinic voice
    assert _voice_for_lang(b, "en") == "padmaja"    # catalog voices are multilingual

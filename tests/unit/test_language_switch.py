"""Language switching (Vinay 2026-07-03 case 2): English as a 9th language,
per-caller mapping plumbing, switch directive in the prompt, and the
voice fallback for a switched language."""
from types import SimpleNamespace

from agent.i18n import LANGUAGES, get_lang, get_lines, get_switch_ack, get_welcome
from agent.livekit_minimal.agent import _voice_for_lang
from agent.prompts.system_prompt import build_system_prompt


def test_english_is_a_supported_language():
    assert "en" in LANGUAGES
    cfg = get_lang("en")
    assert cfg.stt_code == "en-IN"       # Sarvam Saaras
    assert cfg.tts_code == "en"          # Soniox language code
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
        assert "any explicit ask" in p
        assert "DOES NOT SWITCH YOU: code-mixing" in p
        # Live test 2026-07-03: the LLM spoke its own ack alongside the tool
        # call (double-voice) — the switch turn must be silent.
        assert "no permission, no announcing" in p


def test_solo_cap_copy_says_ten_minutes():
    """Vinay 2026-07-03: solo per-call cap raised 4 -> 10 minutes."""
    p = build_system_prompt(
        clinic_name="Test", doctors=[], emergency_contact="9",
        plan="solo", language="te",
    )
    assert "Solo call ends at 10 min" in p
    assert "4 minutes" not in p


def _branch(voice, clones=None):
    return SimpleNamespace(tts_voice=voice, cloned_voices=clones or [])


def test_voice_for_lang_keeps_catalog_voice():
    b = _branch("padmaja")
    assert _voice_for_lang(b, "en") == "padmaja"


def test_voice_for_lang_no_voice_set_uses_language_default():
    b = _branch(None)
    assert _voice_for_lang(b, "hi") == get_lang("hi").default_voice


def test_voice_for_lang_ignores_legacy_cloned_voices():
    """Voice CLONING removed 2026-07-24 (Vinay): legacy branches.cloned_voices
    rows are ignored — the chosen tts_voice (or the language default) wins."""
    b = _branch("padmaja", [
        {"voice_id": "clone_te", "name": "Sree", "language": "te"},
    ])
    assert _voice_for_lang(b, "te") == "padmaja"
    assert _voice_for_lang(b, "en") == "padmaja"


def _last_text(chat_ctx):
    c = chat_ctx.items[-1].content
    return c if isinstance(c, str) else " ".join(c)


def test_switch_drift_guard_appends_new_language_lock():
    """Vinay live 2026-07-26: switch fires then reverts to the old language in
    1-2 turns. The carried history (old language) is countered by a recency-
    salient lock appended as the LAST ctx item, naming the NEW language."""
    from livekit.agents.llm import ChatContext
    from agent.livekit_minimal.agent import _append_switch_drift_guard

    cc = ChatContext.empty()
    cc.add_message(role="assistant", content="పంటి సమస్యా అండి? సరే.")  # old (te) turn
    cc.add_message(role="user", content="can you speak in english")
    _append_switch_drift_guard(cc, "en")

    last = cc.items[-1]
    text = _last_text(cc)
    assert last.role == "user"                 # rides as the freshest turn
    assert "English" in text                   # names the NEW language
    assert "only" in text.lower()              # a hard lock, not a hint
    assert "do not copy" in text.lower()       # neutralises the old turns


def test_telugu_style_turns_flag_wired():
    """#465: VOICE_TELUGU_STYLE_TURNS=1 drops the semantic turn detector for ALL
    languages (VAD + endpoint only, like Telugu) — a reversible latency experiment
    for non-native English/Hindi where the native-trained model extends the wait."""
    import inspect

    import agent.livekit_minimal.agent as ag

    assert hasattr(ag, "_TELUGU_STYLE_TURNS")
    ep = inspect.getsource(ag.entrypoint)
    # the flag OR the te-IN check both force turn_detection=None
    assert "_TELUGU_STYLE_TURNS or lang_cfg.stt_code" in ep


def test_switch_ack_preclip_wired():
    """#464: the switch ack is pre-synthesized once per worker (default voice) and
    replayed on switch, instead of a ~2.3s live cold-connect synth every switch."""
    import inspect

    import agent.livekit_minimal.agent as ag

    assert hasattr(ag, "_prewarm_switch_ack_clips")
    assert isinstance(ag._SWITCH_ACK_CLIPS, dict)
    sw = inspect.getsource(ag.VachanamAgent.__dict__["switch_language"])
    assert "_SWITCH_ACK_CLIPS.get(code)" in sw          # cache lookup on switch
    assert "_switch_ack_frames = _cached_ack" in sw     # replay cached frames
    # the live pre-synth is now gated on the cache miss
    assert '_switch_ack_frames", None) is None' in sw
    ep = inspect.getsource(ag.entrypoint)
    assert "_prewarm_switch_ack_clips()" in ep and "_switch_ack_clips_started" in ep


def test_switch_drift_guard_uses_target_language_name_and_is_noop_on_none():
    from livekit.agents.llm import ChatContext
    from agent.livekit_minimal.agent import _append_switch_drift_guard

    cc = ChatContext.empty()
    _append_switch_drift_guard(cc, "hi")
    assert get_lang("hi").name in _last_text(cc)   # "Hindi", not a code
    _append_switch_drift_guard(None, "hi")         # missing ctx must not raise

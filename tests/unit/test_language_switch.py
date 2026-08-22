"""Language switching (Vinay 2026-07-03 case 2): English as a 9th language,
per-caller mapping plumbing, switch directive in the prompt, and the
voice fallback for a switched language."""
from types import SimpleNamespace

import pytest

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


@pytest.mark.parametrize(
    ("utterance", "expected"),
    [
        ("Telugu lo matladandi", "te"),
        ("English please", "en"),
        ("Hindi mein baat kijiye", "hi"),
        ("Tamil la pesunga", "ta"),
        ("Kannada dalli matadi", "kn"),
        ("Malayalam il samsarikkamo", "ml"),
        ("Marathi madhe bola", "mr"),
        ("Bangla te kotha bolun", "bn"),
        ("aapko Hindi aata hai?", "hi"),
        ("Aapko Hindi aati hai kya?", "hi"),
        ("क्या आपको हिंदी आती है?", "hi"),
        ("మీకు హిందీ వచ్చా?", "hi"),
        ("Do you know Hindi?", "hi"),
        ("in English", "en"),
        ("English only", "en"),
        ("only English", "en"),
        ("keep it English", "en"),
        ("stick to English", "en"),
        ("English from now on", "en"),
        ("in Hindi", "hi"),
        ("Hindi only", "hi"),
        ("in Telugu", "te"),
        ("Telugu only", "te"),
        ("മലയാളം", "ml"),
        ("বাংলা", "bn"),
    ],
)
def test_common_short_language_requests_switch_without_llm(utterance, expected):
    from agent.livekit_minimal.agent import _explicit_language_request

    assert _explicit_language_request(utterance) == expected


@pytest.mark.parametrize(
    "utterance",
    [
        "Does the doctor speak English?",
        "Which languages do you support?",
        "My school language was Hindi but I need an appointment.",
        "Can you compare Telugu and English?",
        "Mere friend ko Hindi aata hai, I need an appointment.",
    ],
)
def test_language_mentions_do_not_accidentally_switch(utterance):
    from agent.livekit_minimal.agent import _explicit_language_request

    assert _explicit_language_request(utterance) is None


def test_prompt_carries_switch_directive_in_all_languages():
    for code in ("te", "en", "hi"):
        p = build_system_prompt(
            clinic_name="Test", doctors=[], emergency_contact="9",
            plan="clinic", language=code,
        )
        assert "switch_language" in p
        # Explicit-ask only — never speech auto-detect (2026-06-17 decision).
        assert "EXPLICIT SWITCH TRIGGER" in p
        assert "DOES NOT switch your language" in p
        # Live test 2026-07-03: the LLM spoke its own ack alongside the tool
        # call (double-voice) — the switch turn must be silent.
        assert "Execute tool `switch_language(code)` IMMEDIATELY" in p


def test_solo_cap_copy_says_ten_minutes():
    """Vinay 2026-07-03: solo per-call cap raised 4 -> 10 minutes."""
    p = build_system_prompt(
        clinic_name="Test", doctors=[], emergency_contact="9",
        plan="solo", language="te",
    )
    assert "Solo call limit: 10 mins" in p
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


def test_turn_detector_follows_active_handoff_language():
    """A Hindi-started call must not retain the semantic detector after an
    explicit Telugu/English handoff; those languages use the measured faster
    VAD path. Hindi and other supported languages retain semantic protection."""
    import inspect

    import agent.livekit_minimal.agent as ag

    assert hasattr(ag, "_TELUGU_STYLE_TURNS")
    init = inspect.getsource(ag.VachanamAgent.__init__)
    assert 'lang_code in ("te", "en")' in init
    assert 'overrides["turn_detection"]' in init
    ep = inspect.getsource(ag.entrypoint)
    assert '"turn_detection": None' in ep
def test_switch_ack_is_synthesized_only_for_an_actual_switch():
    """A normal call must not synthesize every language acknowledgement.

    The requested language still gets its one-word acknowledgement synthesized
    before handoff, with the live-say fallback retained on provider failure.
    """
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
    assert "_prewarm_switch_ack_clips()" not in ep
    assert "async for ev in _new_tts.synthesize(_ack_text)" in sw
    assert "switch_ack_presynth_failed" in sw


def test_switch_drift_guard_trims_long_history():
    """#466: a long old-language history is trimmed to a recent window on switch
    so it can't out-vote the new language; the lock is still the last item."""
    from livekit.agents.llm import ChatContext
    from agent.livekit_minimal.agent import _append_switch_drift_guard, _SWITCH_CTX_KEEP

    cc = ChatContext.empty()
    for i in range(30):
        cc.add_message(role="assistant", content=f"పంటి {i}")  # 30 old (te) turns
    _append_switch_drift_guard(cc, "en")
    # kept window + the appended lock
    assert len(cc.items) <= _SWITCH_CTX_KEEP + 1
    assert "English" in _last_text(cc)  # lock is last


def test_switch_drift_guard_uses_target_language_name_and_is_noop_on_none():
    from livekit.agents.llm import ChatContext
    from agent.livekit_minimal.agent import _append_switch_drift_guard

    cc = ChatContext.empty()
    _append_switch_drift_guard(cc, "hi")
    assert get_lang("hi").name in _last_text(cc)   # "Hindi", not a code
    _append_switch_drift_guard(None, "hi")         # missing ctx must not raise

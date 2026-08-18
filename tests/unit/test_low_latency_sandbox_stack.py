"""Guards for the isolated Soniox latency sandbox."""
from __future__ import annotations

from pathlib import Path

import pytest


def test_production_provider_defaults_are_unchanged():
    from backend.config import Settings

    cfg = Settings()
    assert cfg.stt_provider == "auto"
    assert cfg.tts_provider == "soniox"
    assert cfg.llm_provider == "gemini"
    assert cfg.voice_prompt_cache is False


def test_production_disables_paid_explicit_prompt_storage():
    prod = Path("infra/fly.agent.toml").read_text(encoding="utf-8")
    assert 'VOICE_PROMPT_CACHE = "0"' in prod


def test_pulse_alias_and_minimum_eou_are_validated():
    from backend.config import Settings

    assert Settings(stt_provider="pulse").stt_provider == "smallest"
    with pytest.raises(ValueError, match="100 and 10000"):
        Settings(smallest_eou_timeout_ms=60)


def test_pulse_factory_is_language_pinned(monkeypatch):
    from agent.livekit_minimal import agent as ag
    from agent.i18n import get_lang

    monkeypatch.setattr(ag.settings, "stt_provider", "smallest")
    monkeypatch.setattr(ag.settings, "smallest_api_key", "test-key")
    monkeypatch.setattr(ag.settings, "smallest_model", "pulse")
    monkeypatch.setattr(ag.settings, "smallest_eou_timeout_ms", 100)

    stt = ag._build_stt(get_lang("te"))
    assert stt._opts.model == "pulse"
    assert stt._opts.language == "te"
    assert stt._opts.eou_timeout_ms == 100


def test_cartesia_default_supports_telugu():
    from backend.config import Settings

    assert Settings().cartesia_model == "sonic-3-2026-01-12"


def test_sandbox_is_isolated_and_latency_tuned():
    cfg = Path("infra/fly.agent-sandbox.toml").read_text(encoding="utf-8")
    prod = Path("infra/fly.agent.toml").read_text(encoding="utf-8")

    assert 'app = "vachanam-agent-sandbox"' in cfg
    assert 'primary_region = "bom"' in cfg
    assert 'LIVEKIT_AGENT_NAME = "vachanam-sandbox"' in cfg
    assert 'STT_PROVIDER = "soniox"' in cfg
    assert 'TTS_PROVIDER = "cartesia"' in cfg
    assert 'LLM_PROVIDER = "gemini"' in cfg
    assert "gemini-3.5-flash-lite" not in cfg
    assert "LIVEKIT_INFERENCE_MODEL" not in cfg
    assert 'CARTESIA_VOICE = "07bc462a-c644-49f1-baf7-82d5599131be"' in cfg
    assert 'CARTESIA_MIN_SENTENCE_LEN = "4"' in cfg
    # 2026-08-12: 0/0.06 ended the caller's turn after 60ms of silence, so a
    # mid-sentence pause truncated the question and the agent answered a
    # fragment. Vinay asked which doctors the clinic has and the transcript
    # recorded only "అంటే, మీ దగ్గర ఎవరైనా డాక్టర్" (session 6a3695d7). Back to
    # the config.py defaults; the measured cost was +81ms per turn.
    assert 'VOICE_ENDPOINTING_MIN_DELAY_S = "0.05"' in cfg
    assert 'VOICE_ENDPOINTING_MAX_DELAY_S = "0.30"' in cfg
    assert 'SONIOX_MANUAL_FINALIZE_DELAY_MS = "200"' in cfg
    assert 'VOICE_NUM_IDLE_PROCESSES = "1"' in cfg
    assert 'VOICE_TOOL_PREFETCH = "true"' in cfg
    assert 'VOICE_DETERMINISTIC_CONFIRM = "true"' in cfg
    assert 'MAX_CALL_DURATION_SECONDS = "600"' in cfg
    assert 'RECORDING_ENABLED = "false"' in cfg
    assert 'TRANSCRIPT_CAPTURE_ENABLED = "true"' in cfg
    # The tested Soniox profile is now shared with production, but the sandbox
    # identity and test-only recording/transcript controls remain isolated.
    assert 'STT_PROVIDER = "soniox"' in prod
    assert 'TTS_PROVIDER = "soniox"' in prod
    assert 'SONIOX_TTS_SAMPLE_RATE = "16000"' in prod
    # Production carries the same reverted endpointing as the sandbox: 0/0.06
    # truncated callers mid-sentence and made the agent restart sentences it
    # had already begun (2026-08-12).
    assert 'VOICE_ENDPOINTING_MIN_DELAY_S = "0.05"' in prod
    assert 'VOICE_ENDPOINTING_MAX_DELAY_S = "0.30"' in prod
    assert 'SONIOX_ENDPOINT_LATENCY_LEVEL = "1"' in prod
    assert 'SONIOX_MAX_ENDPOINT_DELAY_MS = "2000"' in prod
    assert 'SONIOX_MANUAL_FINALIZE_DELAY_MS = "200"' in prod
    assert 'VOICE_NUM_IDLE_PROCESSES = "4"' in prod
    assert 'VOICE_TOOL_PREFETCH = "true"' in prod
    assert 'VOICE_DETERMINISTIC_CONFIRM = "true"' in prod
    assert "LIVEKIT_AGENT_NAME" not in prod
    assert "RECORDING_ENABLED" not in prod
    assert "TRANSCRIPT_CAPTURE_ENABLED" not in prod


@pytest.mark.parametrize("code", ("te", "en", "hi", "ta", "kn", "ml", "mr", "bn"))
def test_cartesia_sandbox_builds_every_supported_language(monkeypatch, code):
    from agent.livekit_minimal import agent as ag

    monkeypatch.setattr(ag.settings, "cartesia_api_key", "test-key")
    monkeypatch.setattr(ag.settings, "cartesia_voice", "")
    monkeypatch.setattr(ag.settings, "cartesia_min_sentence_len", 4)
    tts = ag._build_cartesia_tts(code)
    assert tts._opts.language == code


def test_non_soniox_stt_disables_soniox_manual_finalization():
    src = Path("agent/livekit_minimal/agent.py").read_text(encoding="utf-8")
    assert 'settings.stt_provider == "soniox"' in src
    assert "and bool(settings.soniox_jp_api_key)" in src
    assert "settings.soniox_manual_finalize_delay_ms if _uses_soniox_stt else 0" in src


def test_provider_aware_prewarm_and_switch_clips():
    import inspect

    from agent.livekit_minimal import agent as ag

    prewarm_src = inspect.getsource(ag._prewarm)
    assert 'if tts_provider == "soniox"' in prewarm_src
    switch_clip_src = inspect.getsource(ag._prewarm_switch_ack_clips)
    assert "_build_session_tts(" in switch_clip_src
    assert "_build_soniox_tts(" not in switch_clip_src


def test_call_start_never_prewarms_all_language_acknowledgements():
    import inspect

    from agent.livekit_minimal import agent as ag

    entrypoint = inspect.getsource(ag.entrypoint)
    assert "asyncio.create_task(_prewarm_switch_ack_clips())" not in entrypoint
    assert "A real switch still pre-synthesizes its one-word ack" in entrypoint


def test_fixed_fillers_use_shared_redis_audio_cache():
    src = Path("agent/livekit_minimal/agent.py").read_text(encoding="utf-8")
    cache_fn = src.split("async def cache_filler_clips", 1)[1].split(
        "def _play_cached_filler", 1
    )[0]
    assert "_filler_shared_cache_key(" in cache_fn
    assert "await _greeting_cache_get(shared_key)" in cache_fn
    assert "await _greeting_cache_set(shared_key, wavs)" in cache_fn
    warmer = src.split("async def _warm_all_clinic_prompt_caches", 1)[1]
    assert '("filler_clips", get_lines(language).fillers)' in warmer
    assert '("wait_clips", get_wait_fillers(language))' in warmer


def test_tool_filler_synthesis_starts_after_session_and_greeting():
    src = Path("agent/livekit_minimal/agent.py").read_text(encoding="utf-8")
    start = src.index("await _start_task", src.index("async def _cache_tool_fillers"))
    fillers = src.index(
        "_filler_cache_task = asyncio.create_task(_cache_tool_fillers())", start
    )
    assert start < fillers


def test_livekit_llm_provider_can_be_selected_without_gemini_cache(monkeypatch):
    from agent.livekit_minimal import agent as ag

    monkeypatch.setattr(ag.settings, "llm_provider", "livekit")
    monkeypatch.setattr(
        ag.settings, "livekit_inference_model", "google/gemma-4-31b-it"
    )
    llm = ag._build_fallback_llm()
    assert llm.model == "google/gemma-4-31b-it"
    assert ag._cached_primary_llm(("b", "te", "d", "h"), "prompt") is None


def test_session_endpointing_uses_deployment_settings():
    src = Path("agent/livekit_minimal/agent.py").read_text(encoding="utf-8")
    assert '"min_delay": settings.voice_endpointing_min_delay_s' in src
    assert '"max_delay": settings.voice_endpointing_max_delay_s' in src
    assert "num_idle_processes=settings.voice_num_idle_processes" in src

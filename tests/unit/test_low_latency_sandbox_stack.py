"""Guards for the isolated Pulse + Cartesia latency sandbox."""
from __future__ import annotations

from pathlib import Path

import pytest


def test_production_provider_defaults_are_unchanged():
    from backend.config import Settings

    cfg = Settings()
    assert cfg.stt_provider == "auto"
    assert cfg.tts_provider == "soniox"
    assert cfg.llm_provider == "gemini"


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
    assert 'CARTESIA_MODEL = "sonic-3-2026-01-12"' in cfg
    assert 'CARTESIA_VOICE = "cf061d8b-a752-4865-81a2-57570a6e0565"' in cfg
    assert 'VOICE_ENDPOINTING_MIN_DELAY_S = "0"' in cfg
    assert 'VOICE_ENDPOINTING_MAX_DELAY_S = "0.06"' in cfg
    assert 'SONIOX_MANUAL_FINALIZE_DELAY_MS = "200"' in cfg
    assert 'VOICE_NUM_IDLE_PROCESSES = "1"' in cfg
    assert 'VOICE_TOOL_PREFETCH = "true"' in cfg
    assert 'VOICE_DETERMINISTIC_CONFIRM = "true"' in cfg
    assert 'MAX_CALL_DURATION_SECONDS = "600"' in cfg
    assert 'RECORDING_ENABLED = "true"' in cfg
    assert 'TRANSCRIPT_CAPTURE_ENABLED = "true"' in cfg
    assert "STT_PROVIDER" not in prod
    assert "TTS_PROVIDER" not in prod


@pytest.mark.parametrize("code", ("te", "en", "hi", "ta", "kn", "ml", "mr", "bn"))
def test_cartesia_sandbox_builds_every_supported_language(monkeypatch, code):
    from agent.livekit_minimal import agent as ag

    monkeypatch.setattr(ag.settings, "cartesia_api_key", "test-key")
    monkeypatch.setattr(ag.settings, "cartesia_voice", "")
    tts = ag._build_cartesia_tts(code)
    assert tts._opts.language == code


def test_non_soniox_stt_disables_soniox_manual_finalization():
    src = Path("agent/livekit_minimal/agent.py").read_text(encoding="utf-8")
    assert 'settings.stt_provider not in ("smallest", "sarvam")' in src
    assert "settings.soniox_manual_finalize_delay_ms if _uses_soniox_stt else 0" in src


def test_cartesia_sandbox_does_not_prewarm_or_preclip_with_soniox():
    import inspect

    from agent.livekit_minimal import agent as ag

    prewarm_src = inspect.getsource(ag._prewarm)
    assert 'if tts_provider == "soniox"' in prewarm_src
    switch_clip_src = inspect.getsource(ag._prewarm_switch_ack_clips)
    assert "_build_session_tts(" in switch_clip_src
    assert "_build_soniox_tts(" not in switch_clip_src


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

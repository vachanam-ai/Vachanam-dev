"""Soniox TTS switch + feasible latency techniques (2026-07-24, Vinay).

Latency-first: prod TTS → Soniox (streaming) with smallest.ai as the RULE-8
fallback, an env kill-switch (TTS_PROVIDER) for instant rollback, a prewarmed
Soniox WS connection (#8), and branch-scoped tool prefetch (#5). Voice cloning
was dropped (Soniox clone quality). These tests pin the wiring; audio quality
is validated on a live call.
"""
from __future__ import annotations

import agent.livekit_minimal.agent as ag


# ── TTS provider seam ───────────────────────────────────────────────────────
def test_soniox_provider_makes_soniox_primary_smallest_fallback(monkeypatch):
    """TTS_PROVIDER=soniox → Soniox streaming primary, smallest WS+REST as the
    RULE-8 fallback so a Soniox outage never kills the clinic line."""
    monkeypatch.setattr(ag.settings, "tts_provider", "soniox", raising=False)
    monkeypatch.setattr(ag.settings, "soniox_api_key", "k-test", raising=False)

    adapter = ag._build_session_tts("sravani", "te")
    prim, *fallbacks = adapter._tts_instances

    assert "soniox" in type(prim).__module__
    assert prim.capabilities.streaming is True
    fb_names = [type(t).__name__ for t in fallbacks]
    assert fb_names == ["_StreamingSmallestTTS", "_HttpSmallestTTS"]


def test_smallest_provider_is_unchanged_rollback_path(monkeypatch):
    """TTS_PROVIDER=smallest → exactly today's chain (instant rollback, no deploy)."""
    monkeypatch.setattr(ag.settings, "tts_provider", "smallest", raising=False)

    adapter = ag._build_session_tts("sravani", "te")
    names = [type(t).__name__ for t in adapter._tts_instances]
    assert names == ["_StreamingSmallestTTS", "_HttpSmallestTTS"]


def test_soniox_falls_back_to_smallest_when_key_missing(monkeypatch):
    """No Soniox key → smallest only (a missing/revoked key can't take the line
    offline — same RULE-8 posture as STT)."""
    monkeypatch.setattr(ag.settings, "tts_provider", "soniox", raising=False)
    monkeypatch.setattr(ag.settings, "soniox_api_key", "", raising=False)

    adapter = ag._build_session_tts("sravani", "te")
    assert type(adapter._tts_instances[0]).__name__ == "_StreamingSmallestTTS"


def test_soniox_unknown_voice_uses_default_but_smallest_keeps_stored_id(monkeypatch):
    """The fleet's tts_voice values are smallest ids (no Soniox voice picker /
    cloning). Soniox primary substitutes the default catalog voice; the smallest
    fallback still uses the real stored id (so the fallback stays valid)."""
    monkeypatch.setattr(ag.settings, "tts_provider", "soniox", raising=False)
    monkeypatch.setattr(ag.settings, "soniox_api_key", "k-test", raising=False)
    monkeypatch.setattr(ag.settings, "soniox_tts_default_voice", "Priya", raising=False)

    adapter = ag._build_session_tts("sravani", "te")  # sravani = smallest id
    prim, streaming_smallest, _ = adapter._tts_instances
    assert prim._opts.voice == "Priya"                    # substituted
    assert streaming_smallest._opts.voice_id == "sravani"  # fallback keeps real id


def test_soniox_known_voice_passes_through(monkeypatch):
    monkeypatch.setattr(ag.settings, "tts_provider", "soniox", raising=False)
    monkeypatch.setattr(ag.settings, "soniox_api_key", "k-test", raising=False)

    adapter = ag._build_session_tts("Meera", "te")
    assert adapter._tts_instances[0]._opts.voice == "Meera"

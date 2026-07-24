"""Soniox TTS switch + feasible latency techniques (2026-07-24, Vinay).

Latency-first: prod TTS → Soniox (streaming) with smallest.ai as the RULE-8
fallback, an env kill-switch (TTS_PROVIDER) for instant rollback, a prewarmed
Soniox WS connection (#8), and branch-scoped tool prefetch (#5). Voice cloning
was dropped (Soniox clone quality). These tests pin the wiring; audio quality
is validated on a live call.
"""
from __future__ import annotations

from pathlib import Path

import agent.livekit_minimal.agent as ag

_SRC = Path("agent/livekit_minimal/agent.py").read_text(encoding="utf-8")


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


# ── #8 TTS prewarm ──────────────────────────────────────────────────────────
class _FakeProc:
    def __init__(self):
        self.userdata: dict = {}


def test_prewarm_builds_default_soniox_tts(monkeypatch):
    """#8: prewarm builds the default-voice Soniox TTS once so the WS/TLS connect
    is off the caller's first turn."""
    monkeypatch.setattr(ag.settings, "tts_provider", "soniox", raising=False)
    monkeypatch.setattr(ag.settings, "soniox_api_key", "k-test", raising=False)
    monkeypatch.setattr(ag.settings, "soniox_tts_default_voice", "Priya", raising=False)

    proc = _FakeProc()
    ag._prewarm_soniox_tts(proc)
    warm = proc.userdata.get("tts_soniox")

    assert warm is not None and "soniox" in type(warm).__module__
    assert warm._opts.voice == "Priya"
    assert warm._opts.language == "te"  # DEFAULT_LANG


def test_prewarm_skips_soniox_tts_on_smallest_or_no_key(monkeypatch):
    monkeypatch.setattr(ag.settings, "tts_provider", "smallest", raising=False)
    proc = _FakeProc()
    ag._prewarm_soniox_tts(proc)
    assert "tts_soniox" not in proc.userdata

    monkeypatch.setattr(ag.settings, "tts_provider", "soniox", raising=False)
    monkeypatch.setattr(ag.settings, "soniox_api_key", "", raising=False)
    proc2 = _FakeProc()
    ag._prewarm_soniox_tts(proc2)
    assert "tts_soniox" not in proc2.userdata


def test_session_reuses_prewarmed_soniox_when_matching(monkeypatch):
    """A call whose (resolved voice, language) match the prewarmed instance reuses
    it — no per-call rebuild, no cold connect."""
    monkeypatch.setattr(ag.settings, "tts_provider", "soniox", raising=False)
    monkeypatch.setattr(ag.settings, "soniox_api_key", "k-test", raising=False)
    monkeypatch.setattr(ag.settings, "soniox_tts_default_voice", "Priya", raising=False)

    warm = ag._build_soniox_tts("Priya", "te")
    # "sravani" resolves to the default Priya → matches the prewarmed te instance
    adapter = ag._build_session_tts("sravani", "te", prewarmed_soniox=warm)
    assert adapter._tts_instances[0] is warm


def test_session_rebuilds_soniox_when_language_differs(monkeypatch):
    monkeypatch.setattr(ag.settings, "tts_provider", "soniox", raising=False)
    monkeypatch.setattr(ag.settings, "soniox_api_key", "k-test", raising=False)

    warm = ag._build_soniox_tts("Priya", "te")
    adapter = ag._build_session_tts("sravani", "hi", prewarmed_soniox=warm)
    assert adapter._tts_instances[0] is not warm
    assert adapter._tts_instances[0]._opts.language == "hi"


def test_prewarm_and_reuse_are_wired_into_agent():
    """#8 wiring: prewarm hook fires in _prewarm and BOTH session-TTS call sites
    (main + language-switch handoff) pass the prewarmed instance for reuse."""
    assert "_prewarm_soniox_tts(proc)" in _SRC
    assert _SRC.count('ctx.proc.userdata.get("tts_soniox")') == 2

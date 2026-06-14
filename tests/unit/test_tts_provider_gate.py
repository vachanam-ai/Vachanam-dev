"""TTS provider gate (Vinay 2026-06-14): opt-in smallest.ai trial.

Default = Sarvam Bulbul (production untouched). TTS_PROVIDER=smallest + a key
switches to the smallest.ai padmaja voice. The switch is fail-safe: smallest
selected but no key must fall back to Sarvam so a call never breaks over a
TTS-trial misconfig (RULE 8).

These patch the TTS constructors with sentinels so we test the GATE branch, not
real audio-provider construction (which needs live keys).
"""
import livekit.plugins.smallestai as _smallestai

import agent.livekit_minimal.agent as A


def _patch_constructors(monkeypatch):
    monkeypatch.setattr(A.sarvam, "TTS", lambda **k: ("sarvam", k))
    monkeypatch.setattr(_smallestai, "TTS", lambda **k: ("smallest", k))


def test_default_provider_is_sarvam(monkeypatch):
    _patch_constructors(monkeypatch)
    monkeypatch.setattr(A.settings, "tts_provider", "sarvam")
    assert A._build_tts("rupali")[0] == "sarvam"


def test_smallest_used_when_flagged_with_key(monkeypatch):
    _patch_constructors(monkeypatch)
    monkeypatch.setattr(A.settings, "tts_provider", "smallest")
    monkeypatch.setattr(A.settings, "smallest_api_key", "sk_test_dummy")
    monkeypatch.setattr(A.settings, "smallest_voice", "padmaja")
    monkeypatch.setattr(A.settings, "smallest_model", "lightning_v3.1")
    provider, kwargs = A._build_tts("rupali")
    assert provider == "smallest"
    assert kwargs["voice_id"] == "padmaja"
    assert kwargs["model"] == "lightning_v3.1"


def test_smallest_without_key_falls_back_to_sarvam(monkeypatch):
    _patch_constructors(monkeypatch)
    monkeypatch.setattr(A.settings, "tts_provider", "smallest")
    monkeypatch.setattr(A.settings, "smallest_api_key", "")
    assert A._build_tts("rupali")[0] == "sarvam"

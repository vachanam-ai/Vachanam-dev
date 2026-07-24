"""Soniox is the sole TTS provider for every production speech path."""
from __future__ import annotations

import io
import wave
from pathlib import Path

import pytest

import agent.livekit_minimal.agent as ag
from agent.livekit_minimal import greeting as gr

AGENT_SRC = Path("agent/livekit_minimal/agent.py").read_text(encoding="utf-8")
GREETING_SRC = Path("agent/livekit_minimal/greeting.py").read_text(encoding="utf-8")


def test_session_tts_is_direct_soniox(monkeypatch):
    monkeypatch.setattr(ag.settings, "soniox_api_key", "k-test")
    tts = ag._build_session_tts("Meera", "te")
    assert "soniox" in type(tts).__module__
    assert tts.capabilities.streaming is True
    assert tts._opts.voice == "Meera"


def test_legacy_voice_uses_soniox_default(monkeypatch):
    monkeypatch.setattr(ag.settings, "soniox_api_key", "k-test")
    monkeypatch.setattr(ag.settings, "soniox_tts_default_voice", "Priya")
    tts = ag._build_session_tts("sravani", "te")
    assert tts._opts.voice == "Priya"


def test_missing_soniox_key_fails_configuration(monkeypatch):
    monkeypatch.setattr(ag.settings, "soniox_api_key", "")
    with pytest.raises(RuntimeError, match="only TTS provider"):
        ag._build_session_tts("Priya", "te")


def test_no_smallest_runtime_or_dependency_remains():
    requirements = Path("agent/livekit_minimal/requirements.txt").read_text().lower()
    backend_requirements = Path("backend/requirements.txt").read_text().lower()
    assert "smallest" not in AGENT_SRC.lower()
    assert "smallest" not in GREETING_SRC.lower()
    assert "livekit-plugins-smallestai" not in requirements
    assert "smallestai" not in backend_requirements


def test_prewarmed_soniox_is_reused(monkeypatch):
    monkeypatch.setattr(ag.settings, "soniox_api_key", "k-test")
    warm = ag._build_soniox_tts("Priya", "te")
    monkeypatch.setattr(warm, "prewarm", lambda: None)
    assert ag._build_session_tts("Priya", "te", warm) is warm


async def test_soniox_greeting_synth_produces_valid_wav(monkeypatch):
    class Frame:
        data = b"\x00\x01" * 480
        sample_rate = 24000
        num_channels = 1

    class Event:
        frame = Frame()

    class FakeTTS:
        def __init__(self, **kwargs):
            pass

        def synthesize(self, text):
            async def gen():
                yield Event()
            return gen()

        async def aclose(self):
            pass

    import livekit.plugins.soniox as sx

    monkeypatch.setattr(sx, "TTS", FakeTTS)
    wav = (await gr.synth_wavs(["నమస్కారం"], "Priya", "te"))[0]
    with wave.open(io.BytesIO(wav), "rb") as audio:
        assert audio.getframerate() == 24000
        assert audio.getnchannels() == 1
        assert audio.getnframes() == 480


def test_settings_voice_catalog_is_soniox_only():
    source = Path("backend/routers/branches.py").read_text(encoding="utf-8")
    section = source.split("async def list_branch_voices")[1].split("async def ", 1)[0]
    for voice in ("Priya", "Meera", "Arjun", "Rohan"):
        assert voice in source
    assert "smallest" not in section.lower()

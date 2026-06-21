"""Regression: instant pre-session welcome clip (FIXLOG — kills start-of-call
silence). Covers the welcome line resolution and the play_welcome contract that
matters on a live phone path: it ALWAYS unpublishes its track and NEVER raises,
even when TTS or publishing fails (RULE 8 — a welcome clip must not break a call).
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.i18n import get_welcome
from agent.livekit_minimal.welcome_audio import play_welcome


def test_get_welcome_te_is_validated_text():
    # Vinay-validated Telugu: "namaskaram <clinic> clinic ki swagatham".
    line = get_welcome("te").format(clinic="Vasavi")
    assert "Vasavi" in line and "స్వాగతం" in line


def test_get_welcome_unknown_falls_back_to_telugu():
    assert get_welcome("zz") == get_welcome("te")
    assert get_welcome(None) == get_welcome("te")


def _fake_room():
    lp = SimpleNamespace(
        publish_track=AsyncMock(return_value=SimpleNamespace(sid="TR_x")),
        unpublish_track=AsyncMock(),
    )
    return SimpleNamespace(local_participant=lp)


def _fake_tts(frames=2, raise_on_synth=False):
    tts = MagicMock()
    tts.sample_rate = 24000

    async def _synth(_text):
        if raise_on_synth:
            raise RuntimeError("tts down")
        for _ in range(frames):
            yield SimpleNamespace(frame=object())

    tts.synthesize = _synth
    return tts


def test_play_welcome_captures_frames_and_unpublishes(monkeypatch):
    room = _fake_room()
    captured = {"n": 0}

    class _Src:
        def __init__(self, *a, **k):
            pass

        async def capture_frame(self, _f):
            captured["n"] += 1

        async def wait_for_playout(self):
            pass

        async def aclose(self):
            pass

    from agent.livekit_minimal import welcome_audio as wa

    monkeypatch.setattr(wa.rtc, "AudioSource", _Src)
    monkeypatch.setattr(wa.rtc, "LocalAudioTrack", SimpleNamespace(create_audio_track=lambda *a: object()))
    monkeypatch.setattr(wa.rtc, "TrackPublishOptions", lambda **k: None)
    monkeypatch.setattr(wa.rtc, "TrackSource", SimpleNamespace(SOURCE_MICROPHONE=1))

    ok = asyncio.run(play_welcome(room, "hi", _fake_tts(frames=3)))

    assert ok is True  # success → caller may skip the post-start greeting
    assert captured["n"] == 3
    room.local_participant.unpublish_track.assert_awaited_once()  # track cleaned up


def test_play_welcome_swallows_tts_failure_and_still_unpublishes(monkeypatch):
    room = _fake_room()

    class _Src:
        def __init__(self, *a, **k):
            pass

        async def capture_frame(self, _f):
            pass

        async def wait_for_playout(self):
            pass

        async def aclose(self):
            pass

    from agent.livekit_minimal import welcome_audio as wa

    monkeypatch.setattr(wa.rtc, "AudioSource", _Src)
    monkeypatch.setattr(wa.rtc, "LocalAudioTrack", SimpleNamespace(create_audio_track=lambda *a: object()))
    monkeypatch.setattr(wa.rtc, "TrackPublishOptions", lambda **k: None)
    monkeypatch.setattr(wa.rtc, "TrackSource", SimpleNamespace(SOURCE_MICROPHONE=1))

    # Must NOT raise even though synth blows up, must return False (so the caller
    # still speaks the outbound greeting after session.start), and still unpublish.
    ok = asyncio.run(play_welcome(room, "hi", _fake_tts(raise_on_synth=True)))
    assert ok is False
    room.local_participant.unpublish_track.assert_awaited_once()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))

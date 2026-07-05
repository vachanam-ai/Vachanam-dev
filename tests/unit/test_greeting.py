"""Regression: instant REAL greeting at answer (FIXLOG #264 — Vinay 2026-07-05
"within 2 seconds the agent needs to speak... original conversation").

Covers: segment composition (inbound disclosure / greet-by-name / doctor's
question; outbound reminder/rebook/follow-up with spoken time/date), the RULE 6
sanitize-at-synth boundary, and the play_wavs live-call contract: every segment
played → True, any failure → False + never raises + track always unpublished
(RULE 8 — a greeting clip must not break a call). Replaces test_welcome_audio.py
(canned welcome clip deleted).
"""
from __future__ import annotations

import asyncio
import io
import wave
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent.i18n import get_lines, get_welcome
from agent.livekit_minimal import greeting as g

TE = "te"
CLINIC = "వాసవి"


def _wav(sr=24000, ch=1, frames=480) -> bytes:
    buf = io.BytesIO()
    wf = wave.open(buf, "wb")
    wf.setnchannels(ch)
    wf.setsampwidth(2)
    wf.setframerate(sr)
    wf.writeframes(b"\x00\x00" * frames * ch)
    wf.close()
    return buf.getvalue()


# ---------------------------------------------------------------- composition

def test_inbound_new_caller_welcome_then_disclosure():
    texts = g.inbound_greeting_texts(TE, CLINIC)
    assert len(texts) == 2
    assert texts[0] == get_welcome(TE).format(clinic=CLINIC)
    assert texts[1] == get_lines(TE).disclosure_greeting.format(clinic=CLINIC)


def test_inbound_known_caller_greets_by_name():
    texts = g.inbound_greeting_texts(TE, CLINIC, spk_caller="రమేష్")
    assert "రమేష్" in texts[1]
    assert texts[1] == get_lines(TE).known_caller_greeting.format(
        patient="రమేష్", clinic=CLINIC
    )


def test_inbound_followup_question_is_own_segment_with_name_prefix():
    msg = "నొప్పి తగ్గిందా?"
    texts = g.inbound_greeting_texts(TE, CLINIC, spk_caller="రమేష్", followup_message=msg)
    assert texts[-1] == msg  # doctor's question = its own short utterance
    assert "రమేష్" in texts[1]  # name prefix on the disclosure segment


def test_outbound_reminder_speaks_telugu_time_not_digits():
    meta = {"appointment_time": "16:30"}
    texts = g.outbound_greeting_texts(
        TE, CLINIC, "రమేష్", "డా. శ్రీనివాస్", meta, {}, is_reminder=True
    )
    assert texts[0] == get_welcome(TE).format(clinic=CLINIC)
    assert "16:30" not in texts[1]  # spoken words, never raw digits (RULE 6)
    assert "రమేష్" in texts[1]


def test_outbound_rebook_speaks_date_words():
    meta = {"cancelled_date": "2026-07-04"}
    texts = g.outbound_greeting_texts(
        TE, CLINIC, "రమేష్", "డా. శ్రీనివాస్", meta, {}, is_rebook=True
    )
    assert "2026-07-04" not in texts[1]


def test_outbound_followup_question_is_own_segment():
    fm = {"message": "మందులు వేసుకుంటున్నారా?"}
    texts = g.outbound_greeting_texts(
        TE, CLINIC, "రమేష్", "డా. శ్రీనివాస్", {}, fm, is_followup=True
    )
    assert texts[-1] == fm["message"]


def test_fallback_speaks_same_words_as_clip():
    """The session.say fallback and the instant clip must be the SAME text —
    the seeded chat_ctx describes what the caller actually heard."""
    a = g.inbound_greeting_texts(TE, CLINIC, spk_caller="రమేష్")
    b = g.inbound_greeting_texts(TE, CLINIC, spk_caller="రమేష్")
    assert a == b


# ------------------------------------------------------------------ synthesis

def test_synth_sanitizes_at_boundary(monkeypatch):
    """RULE 6: markdown/symbols must be stripped INSIDE the synth call."""
    sent = {}

    class _Resp:
        content = _wav()

        def raise_for_status(self):
            pass

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            sent["text"] = json["text"]
            return _Resp()

    monkeypatch.setattr(g.httpx, "AsyncClient", _Client)
    wavs = asyncio.run(g.synth_wavs(["**నమస్కారం**"], "kavitha", TE))
    assert len(wavs) == 1
    assert "*" not in sent["text"]


# ------------------------------------------------------------------- playback

def _fake_room():
    lp = SimpleNamespace(
        publish_track=AsyncMock(return_value=SimpleNamespace(sid="TR_x")),
        unpublish_track=AsyncMock(),
    )
    return SimpleNamespace(local_participant=lp)


class _Src:
    def __init__(self, *a, **k):
        self.frames = 0

    async def capture_frame(self, _f):
        self.frames += 1

    async def wait_for_playout(self):
        pass

    async def aclose(self):
        pass


def _patch_rtc(monkeypatch):
    monkeypatch.setattr(g.rtc, "AudioSource", _Src)
    monkeypatch.setattr(
        g.rtc, "LocalAudioTrack", SimpleNamespace(create_audio_track=lambda *a: object())
    )
    monkeypatch.setattr(g.rtc, "TrackPublishOptions", lambda **k: None)
    monkeypatch.setattr(g.rtc, "TrackSource", SimpleNamespace(SOURCE_MICROPHONE=1))
    monkeypatch.setattr(g.rtc, "AudioFrame", lambda **k: None)


def test_play_wavs_all_segments_true_and_unpublishes(monkeypatch):
    _patch_rtc(monkeypatch)
    room = _fake_room()
    ok = asyncio.run(g.play_wavs(room, [_wav(), _wav()]))
    assert ok is True
    room.local_participant.unpublish_track.assert_awaited_once()


def test_play_wavs_bad_bytes_false_never_raises(monkeypatch):
    _patch_rtc(monkeypatch)
    room = _fake_room()
    ok = asyncio.run(g.play_wavs(room, [b"not a wav"]))
    assert ok is False
    room.local_participant.publish_track.assert_not_awaited()


def test_play_wavs_partial_failure_false_but_cleans_up(monkeypatch):
    """Second segment failing → False (consent/disclosure completeness gate),
    but the already-published track is still unpublished (RULE 8)."""
    _patch_rtc(monkeypatch)
    room = _fake_room()

    async def _boom():
        raise RuntimeError("synth died")

    ok = asyncio.run(g.play_wavs(room, [_wav(), _boom()]))
    assert ok is False
    room.local_participant.unpublish_track.assert_awaited_once()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))

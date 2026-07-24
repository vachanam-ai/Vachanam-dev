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

from agent.i18n import get_lines, get_recording_notice, get_welcome
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

def test_inbound_new_caller_trimmed_single_intro():
    # #302 (Vinay 2026-07-10): plain inbound = ONE trimmed sentence, not
    # welcome + disclosure.
    texts = g.inbound_greeting_texts(TE, CLINIC)
    assert len(texts) == 1
    assert texts[0] == get_lines(TE).inbound_intro.format(clinic=CLINIC)


def test_recording_notice_is_first_and_gated_for_inbound():
    normal = g.inbound_greeting_texts(TE, CLINIC)
    recorded = g.inbound_greeting_texts(TE, CLINIC, recording_active=True)
    assert get_recording_notice(TE) not in normal
    assert recorded[0] == get_recording_notice(TE)
    assert recorded[1:] == normal


def test_inbound_known_caller_greets_by_name():
    texts = g.inbound_greeting_texts(TE, CLINIC, spk_caller="రమేష్")
    assert len(texts) == 1  # #302 trimmed single intro
    assert texts[0] == get_lines(TE).inbound_intro_known.format(
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


def test_recording_notice_is_first_and_gated_for_outbound():
    kwargs = dict(is_reminder=True, recording_active=True)
    recorded = g.outbound_greeting_texts(
        TE, CLINIC, "రమేష్", "డా. శ్రీనివాస్",
        {"appointment_time": "16:30"}, {}, **kwargs
    )
    assert recorded[0] == get_recording_notice(TE)
    assert recorded[1] == get_welcome(TE).format(clinic=CLINIC)


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
    sent = []

    class _Frame:
        data = b"\x00\x00" * 480
        sample_rate = 24000
        num_channels = 1

    class _Event:
        frame = _Frame()

    class _FakeTTS:
        def __init__(self, **kwargs):
            pass

        def synthesize(self, text):
            sent.append(text)

            async def _gen():
                yield _Event()
            return _gen()

        async def aclose(self):
            pass

    import livekit.plugins.soniox as sx

    monkeypatch.setattr(sx, "TTS", _FakeTTS)
    wavs = asyncio.run(g.synth_wavs(["**నమస్కారం**"], "Priya", TE))
    assert len(wavs) == 1
    assert sent == ["నమస్కారం"]


def test_normalize_pcm_boosts_quiet_and_leaves_loud():
    import numpy as np

    quiet = (np.sin(np.linspace(0, 200, 4800)) * 1500).astype(np.int16).tobytes()
    out = np.frombuffer(g.normalize_pcm(quiet), dtype=np.int16)
    assert np.abs(out).max() > 8000  # boosted (max_gain-capped), audible on a phone
    loud = (np.sin(np.linspace(0, 200, 4800)) * 30000).astype(np.int16).tobytes()
    assert g.normalize_pcm(loud) == loud  # already loud — untouched
    assert g.normalize_pcm(b"") == b""  # empty/silence never crashes


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


# ── FIXLOG #302: trimmed one-sentence inbound intro (Vinay 2026-07-10) ───────


def test_te_inbound_intro_is_single_trimmed_segment():
    """Plain te inbound greeting = ONE sentence (Vinay's exact wording), not
    the old welcome + disclosure pair; AI disclosure (DPDP) must survive."""
    out = g.inbound_greeting_texts("te", "క్లినిక్")
    assert len(out) == 1
    assert out[0].startswith("నమస్కారం")
    assert "AI అసిస్టెంట్‌ని మాట్లాడుతున్నాను" in out[0]  # disclosure kept
    assert "స్వాగతం" not in out[0]  # old welcome-clip wording gone


def test_te_known_caller_intro_greets_by_name_single_segment():
    out = g.inbound_greeting_texts("te", "క్లినిక్", spk_caller="రవి")
    assert len(out) == 1
    assert "చెప్పండి రవి గారు" in out[0]
    assert "AI అసిస్టెంట్‌ని మాట్లాడుతున్నాను" in out[0]


def test_trim_does_not_touch_followup_or_other_languages():
    """Follow-up path keeps welcome+message. (2026-07-14, Vinay: the trimmed
    ONE-segment intro now applies to EVERY language, not just Telugu — the
    old two-segment hi assertion is superseded; full coverage lives in
    test_short_intro_all_languages.)"""
    fup = g.inbound_greeting_texts("te", "క్లినిక్", spk_caller="రవి",
                                 followup_message="ఎలా ఉన్నారు?")
    assert len(fup) >= 2
    assert len(g.inbound_greeting_texts("hi", "Clinic")) == 1

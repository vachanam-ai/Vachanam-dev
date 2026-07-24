"""Cached lookup-filler audio (FIXLOG #282).

Vinay 2026-07-06: "cache a response and speak it instantly while checking".
The lookup filler ("okay అండి / ఒక్క నిమిషం") is pre-rendered once at session
start and replayed from cache with no live TTS synth. Covers:
  - _wav_to_pcm decodes a WAV to (pcm, sr, ch)
  - _pcm_frames chunks PCM into 10ms AudioFrames
  - cache_filler_clips stores decoded clips on session.userdata
  - _say_lookup_filler plays cached audio (session.say audio=...) when present,
    falls back to live text synth when the cache is empty
"""
import io
import wave


import agent.livekit_minimal.agent as ag


def _make_wav(seconds=0.05, sr=8000, ch=1) -> bytes:
    n = int(seconds * sr)
    buf = io.BytesIO()
    wf = wave.open(buf, "wb")
    wf.setnchannels(ch)
    wf.setsampwidth(2)
    wf.setframerate(sr)
    wf.writeframes(b"\x10\x00" * n * ch)  # non-silent so normalize keeps it
    wf.close()
    return buf.getvalue()


def test_wav_to_pcm_decodes_rate_and_channels():
    pcm, sr, ch = ag._wav_to_pcm(_make_wav(sr=8000, ch=1))
    assert sr == 8000 and ch == 1
    assert len(pcm) > 0 and len(pcm) % 2 == 0


async def test_pcm_frames_yields_10ms_frames():
    sr, ch = 8000, 1
    pcm, _, _ = ag._wav_to_pcm(_make_wav(seconds=0.05, sr=sr, ch=ch))
    frames = [f async for f in ag._pcm_frames(pcm, sr, ch)]
    assert frames, "expected at least one frame"
    # 10ms at 8kHz = 80 samples/frame
    assert all(f.samples_per_channel == sr // 100 for f in frames)
    assert all(f.sample_rate == sr for f in frames)


class _FakeSession:
    def __init__(self, userdata):
        self.userdata = userdata
        self.said = []  # (text, has_audio)

    def say(self, text, *, audio=None, add_to_chat_ctx=True):
        self.said.append((text, audio is not None))


class _Ctx:
    def __init__(self, session):
        self.session = session


async def test_cache_filler_clips_populates_userdata(monkeypatch):
    ud = {"fillers": ["ఒక్క నిమిషం", "okay అండి"], "filler_clips": []}
    sess = _FakeSession(ud)

    async def _fake_synth(texts, voice_id, lang_code):
        return [_make_wav() for _ in texts]

    monkeypatch.setattr(ag, "synth_wavs", _fake_synth)
    await ag.cache_filler_clips(sess, ud["fillers"], "voice", "te")

    clips = ud["filler_clips"]
    assert len(clips) == 2
    assert {c["text"] for c in clips} == set(ud["fillers"])
    assert all(c["pcm"] and c["sr"] and c["ch"] for c in clips)


async def test_soniox_filler_cache_preserves_long_pause(monkeypatch):
    line = "ఒక్క నిమిషం అండి... చూస్తున్నాను. [long pause]"
    ud = {"wait_fillers": [line], "wait_clips": []}
    sess = _FakeSession(ud)
    captured = []

    async def _fake_synth(texts, voice_id, lang_code):
        captured.extend(texts)
        return [_make_wav() for _ in texts]

    monkeypatch.setattr(ag, "synth_wavs", _fake_synth)
    await ag.cache_filler_clips(
        sess, ud["wait_fillers"], "Priya", "te", key="wait_clips"
    )

    assert captured == [line]


def test_say_lookup_filler_uses_cached_audio_when_present():
    pcm, sr, ch = ag._wav_to_pcm(_make_wav())
    ud = {"fillers": ["x"], "filler_clips": [{"text": "okay అండి", "pcm": pcm, "sr": sr, "ch": ch}]}
    sess = _FakeSession(ud)
    ag._say_lookup_filler(_Ctx(sess))
    assert len(sess.said) == 1
    text, has_audio = sess.said[0]
    assert has_audio is True  # played cached audio, not live synth
    assert text == "okay అండి"


def test_say_lookup_filler_falls_back_to_live_text_without_cache():
    ud = {"fillers": ["ఒక్క నిమిషం"], "filler_clips": []}
    sess = _FakeSession(ud)
    ag._say_lookup_filler(_Ctx(sess))
    assert len(sess.said) == 1
    text, has_audio = sess.said[0]
    assert has_audio is False  # no cache → live synth of the filler text
    assert text  # a filler string was spoken

"""smallest.ai voice catalog + cloning service (Vinay 2026-06-15).

The SDK is mocked (no live API in tests, like calendar/Razorpay). Proves:
  - list_voices filters the catalog to a language
  - clone_voice returns the new voice_id from the SDK response
  - a missing key / SDK error surfaces as VoiceServiceError (clean HTTP later),
    never a raw 500
"""
from types import SimpleNamespace as NS

import pytest

import backend.services.smallest_voice as sv


class _FakeWaves:
    def __init__(self, voices):
        self._voices = voices
        self.deleted = []

    def get_voices(self, model):
        return NS(voices=self._voices)

    def add_voice(self, display_name, file):
        # file is a (filename, bytes) tuple
        assert isinstance(file, tuple) and isinstance(file[1], bytes)
        return NS(data=NS(voice_id="voice_clone_abc"), message="ok")

    def delete_voice(self, voice_id):
        self.deleted.append(voice_id)


def _voice(vid, langs, gender="female"):
    return NS(voice_id=vid, display_name=vid.title(), tags=NS(language=langs, gender=gender))


@pytest.fixture
def fake_waves(monkeypatch):
    fw = _FakeWaves([
        _voice("padmaja", ["telugu", "tamil", "kannada", "malayalam"]),
        _voice("niharika", ["hindi", "marathi", "bengali", "odia"]),
        _voice("avery", ["english"], "female"),
    ])
    monkeypatch.setattr(sv, "_waves", lambda: fw)
    return fw


def test_list_voices_filters_by_language(fake_waves):
    # Pass the short code "te"; the service translates it to the full name
    # "telugu" (which is how smallest tags voices) before matching.
    te = sv.list_voices("te")
    ids = [v["voice_id"] for v in te]
    assert "padmaja" in ids and "niharika" not in ids and "avery" not in ids


def test_list_voices_no_filter_returns_all(fake_waves):
    allv = sv.list_voices(None)
    assert {v["voice_id"] for v in allv} == {"padmaja", "niharika", "avery"}
    assert allv[0]["display_name"] and "languages" in allv[0]


def test_clone_voice_returns_voice_id(fake_waves):
    vid = sv.clone_voice("Dr Voice", "sample.wav", b"RIFFfakeaudio")
    assert vid == "voice_clone_abc"


def test_delete_cloned_voice_calls_sdk(fake_waves):
    sv.delete_cloned_voice("voice_clone_abc")
    assert fake_waves.deleted == ["voice_clone_abc"]


def test_missing_key_raises_voice_service_error(monkeypatch):
    monkeypatch.setattr(sv.settings, "smallest_api_key", "")
    with pytest.raises(sv.VoiceServiceError):
        sv.list_voices("te")


def test_sdk_error_normalized_not_raw(monkeypatch):
    class _Boom:
        def get_voices(self, model):
            raise RuntimeError("api 500")
    monkeypatch.setattr(sv, "_waves", lambda: _Boom())
    with pytest.raises(sv.VoiceServiceError):
        sv.list_voices("te")

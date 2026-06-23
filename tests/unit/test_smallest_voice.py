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


def test_clone_voice_returns_voice_id(fake_waves, monkeypatch):
    # clone_voice() posts to smallest.ai with raw httpx (NOT the mocked SDK), so
    # mock httpx.post here — otherwise the test hits the live API and 500s.
    import httpx

    class _Resp:
        status_code = 200
        content = b"{}"
        text = ""

        def json(self):
            return {"voiceId": "voice_clone_abc"}

    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp())
    vid = sv.clone_voice("Dr Voice", "sample.wav", b"RIFFfakeaudio")
    assert vid == "voice_clone_abc"


def test_delete_cloned_voice_calls_sdk(fake_waves):
    sv.delete_cloned_voice("voice_clone_abc")
    assert fake_waves.deleted == ["voice_clone_abc"]


def _vd(vid, gender):
    return {"voice_id": vid, "display_name": vid, "gender": gender, "languages": ["telugu"]}


def test_select_top_caps_3_female_2_male_default_first():
    catalog = [
        _vd("f1", "female"), _vd("m1", "male"), _vd("f2", "Female"),
        _vd("f3", "female"), _vd("m2", "MALE"), _vd("f4", "female"),
        _vd("m3", "male"), _vd("nb", None),
    ]
    out = sv._select_top(catalog, default_id="f4")
    ids = [v["voice_id"] for v in out]
    assert len(out) == 5
    assert sum((v["gender"] or "").lower() == "female" for v in out) == 3
    assert sum((v["gender"] or "").lower() == "male" for v in out) == 2
    assert ids[0] == "f4"          # default pulled to front of its bucket
    assert "nb" not in ids          # genderless excluded


def test_select_top_short_buckets_yield_fewer():
    out = sv._select_top([_vd("f1", "female"), _vd("m1", "male")])
    assert [v["voice_id"] for v in out] == ["f1", "m1"]  # 1F+1M, no padding


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

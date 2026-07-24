"""smallest.ai voice catalog service (Vinay 2026-06-15; cloning REMOVED 2026-07-24).

The SDK is mocked (no live API in tests, like calendar/Razorpay). Proves:
  - list_voices filters the catalog to a language
  - a missing key / SDK error surfaces as VoiceServiceError (clean HTTP later),
    never a raw 500
"""
from types import SimpleNamespace as NS

import pytest

import backend.services.smallest_voice as sv


class _FakeWaves:
    def __init__(self, voices):
        self._voices = voices

    def get_voices(self, model):
        return NS(voices=self._voices)



def _voice(vid, langs, gender="female"):
    return NS(voice_id=vid, display_name=vid.title(), tags=NS(language=langs, gender=gender))


@pytest.fixture
def fake_waves(monkeypatch):
    fw = _FakeWaves([
        _voice("padmaja", ["telugu", "tamil", "kannada", "malayalam"]),
        _voice("niharika", ["hindi", "marathi", "bengali"]),
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


def test_list_voices_injects_pro_sravani_405(fake_waves):
    """#405: sravani lives in the PRO catalog (not the standard list the API
    returns) — the picker must still offer her for Telugu, FIRST (she's the te
    default), and never for other languages."""
    te = sv.list_voices("te")
    assert te[0]["voice_id"] == "sravani"
    assert te[0]["display_name"] == "Sravani"
    hi = sv.list_voices("hi")
    assert "sravani" not in [v["voice_id"] for v in hi]


def test_list_voices_no_filter_returns_all(fake_waves):
    # _select_top keeps 3 female + 2 male; with sravani injected the 4-female
    # pool trims to the first three (avery drops — catalog order, no default).
    allv = sv.list_voices(None)
    assert {v["voice_id"] for v in allv} == {"sravani", "padmaja", "niharika"}
    assert allv[0]["display_name"] and "languages" in allv[0]


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

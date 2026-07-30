"""Offline transliteration (indic-transliteration; replaced Sarvam 2026-07-30).

Two guarantees this module owns:
  1. TTS names (RULE 6, prod bug 2026-06-23): a Latin name in an Indic call is
     rendered into that script so TTS speaks it instead of spelling "S R I N I".
  2. Cross-script MATCH keys (#467 identity, #294 doctor): Indic→ASCII romanize
     + phonetic_fold collapse the ś/sh/s · v/w · aspiration-h spelling gap so a
     Telugu-spoken name matches the Latin record.
On any library failure the original text is returned (RULE 8). Cached in-proc.
"""
import pytest

from agent.i18n import transliterate as tl


@pytest.fixture(autouse=True)
def _clear_cache():
    tl._cache.clear()
    yield
    tl._cache.clear()


# ── spoken_name: Latin → call-script for TTS (RULE 6) ──

@pytest.mark.asyncio
async def test_empty_name_is_noop():
    assert await tl.spoken_name("", "te") == ""
    assert await tl.spoken_name(None, "te") == ""


@pytest.mark.asyncio
async def test_already_indic_name_is_noop():
    # No Latin letters → returned unchanged (nothing to render).
    assert await tl.spoken_name("శ్రీనివాస్", "te") == "శ్రీనివాస్"


@pytest.mark.asyncio
async def test_english_call_is_noop():
    assert await tl.spoken_name("Srinivas", "en") == "Srinivas"


@pytest.mark.asyncio
async def test_latin_name_rendered_into_call_script():
    out = await tl.spoken_name("Srinivas", "te")
    assert out != "Srinivas"
    assert tl._detect_script(out) == "te-IN"   # now Telugu script


@pytest.mark.asyncio
async def test_result_is_cached():
    await tl.spoken_name("Srinivas", "te")
    assert ("Srinivas", "te-IN") in tl._cache   # second call is served from here


@pytest.mark.asyncio
async def test_failure_falls_back_to_original(monkeypatch):
    # RULE 8: a library outage must return the raw name, never raise.
    def boom(*a, **k):
        raise RuntimeError("sanscript down")
    monkeypatch.setattr(tl, "_sanscript", boom)
    assert await tl.spoken_name("Srinivas", "te") == "Srinivas"


# ── romanize + phonetic_fold: cross-script MATCH keys (#467 / #294) ──

def test_romanize_indic_to_ascii():
    out = tl.romanize("శ్రీనివాస్", "te-IN")
    assert out.isascii()
    assert "srinivas" in out.lower()


def test_romanize_latin_passthrough():
    assert tl.romanize("Vinay") == "Vinay"


@pytest.mark.parametrize("spoken_native,stored_latin", [
    ("వినయ్", "Vinay"),
    ("శ్రీనివాస్", "Srinivas"),
    ("లక్ష్మి", "Lakshmi"),          # ksh/ś spelling gap
    ("రవి", "Ravi"),
])
def test_fold_bridges_crossscript_spelling(spoken_native, stored_latin):
    """The folded key of an Indic name equals the folded key of its Latin
    spelling — this is what keeps #467 identity from locking callers out."""
    assert tl.phonetic_fold(tl.romanize(spoken_native)) == tl.phonetic_fold(stored_latin)


def test_fold_keeps_distinct_names_apart():
    assert tl.phonetic_fold(tl.romanize("రవి")) != tl.phonetic_fold("Kavi")
    assert tl.phonetic_fold(tl.romanize("వినయ్")) != tl.phonetic_fold("Vijay")

"""Regression: outbound greetings must speak names, not spell Latin letters.

Bug (prod 2026-06-23): reminder call said the doctor's name "Srinivas" as
"S R I N I" — Latin glyphs in a Telugu sentence are read letter-by-letter by
TTS. spoken_name() transliterates Latin names to the call script (RULE 6),
no-ops for already-Indic names, and falls back to the raw name on any error
(RULE 8). Result is cached in-process.
"""
import pytest

from agent.i18n import transliterate as tl

pytestmark = pytest.mark.asyncio


class _FakeResp:
    def __init__(self, text):
        self._text = text

    def raise_for_status(self):
        pass

    def json(self):
        return {"transliterated_text": self._text}


class _FakeClient:
    """Stand-in for httpx.AsyncClient — records calls, returns a canned name."""

    calls = 0

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, *a, **k):
        type(self).calls += 1
        return _FakeResp("శ్రీనివాస్")


@pytest.fixture(autouse=True)
def _clear_cache():
    tl._cache.clear()
    _FakeClient.calls = 0
    yield
    tl._cache.clear()


async def test_empty_name_is_noop():
    assert await tl.spoken_name("", "te") == ""
    assert await tl.spoken_name(None, "te") == ""


async def test_already_indic_name_is_noop(monkeypatch):
    # No Latin letters → returned unchanged, NO network call.
    monkeypatch.setattr(tl.httpx, "AsyncClient", _FakeClient)
    out = await tl.spoken_name("శ్రీనివాస్", "te")
    assert out == "శ్రీనివాస్"
    assert _FakeClient.calls == 0


async def test_latin_name_transliterated(monkeypatch):
    monkeypatch.setattr(tl.httpx, "AsyncClient", _FakeClient)
    out = await tl.spoken_name("Srinivas", "te")
    assert out == "శ్రీనివాస్"
    assert _FakeClient.calls == 1


async def test_result_is_cached(monkeypatch):
    monkeypatch.setattr(tl.httpx, "AsyncClient", _FakeClient)
    await tl.spoken_name("Srinivas", "te")
    await tl.spoken_name("Srinivas", "te")
    assert _FakeClient.calls == 1  # second call served from cache


async def test_failure_falls_back_to_original(monkeypatch):
    class _BoomClient(_FakeClient):
        async def post(self, *a, **k):
            raise ConnectionError("sarvam down")

    monkeypatch.setattr(tl.httpx, "AsyncClient", _BoomClient)
    # RULE 8: a transliterate outage must return the raw name, never raise.
    assert await tl.spoken_name("Srinivas", "te") == "Srinivas"

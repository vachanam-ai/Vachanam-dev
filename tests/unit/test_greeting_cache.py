"""#439 (Vinay 2026-07-21: calls dying at ~15s; root cause = ~16s call-start,
of which ~10s was the welcome greeting synthesized LIVE via smallest.ai on
every call). The STATIC welcome audio is now cached in Redis: first call for a
(branch, lang, voice, text) synths + stores; every call after plays the cached
bytes instantly. Dynamic greetings (caller name / follow-up) stay live.
"""
import asyncio

import pytest

from agent.livekit_minimal import greeting as g


def test_cache_key_changes_with_text():
    k1 = g._greeting_cache_key("b1", "te", "kavya", ["namaskaram A"])
    k2 = g._greeting_cache_key("b1", "te", "kavya", ["namaskaram B"])
    k3 = g._greeting_cache_key("b2", "te", "kavya", ["namaskaram A"])
    assert k1 != k2          # text change → new key (no stale greeting)
    assert k1 != k3          # branch change → new key
    assert k1.startswith("greet:v1:b1:te:kavya:")


@pytest.mark.asyncio
async def test_cache_hit_plays_cached_skips_synth(monkeypatch):
    played = {}
    synthed = {"n": 0}

    async def fake_get(key):
        return [b"CACHED_WAV"]

    async def fake_play(room, wavs, t_answer=None):
        played["wavs"] = wavs
        return True

    async def fake_synth(texts, voice, lang):
        synthed["n"] += 1
        return [b"FRESH"]

    monkeypatch.setattr(g, "_greeting_cache_get", fake_get)
    monkeypatch.setattr(g, "play_wavs", fake_play)
    monkeypatch.setattr(g, "synth_wavs", fake_synth)

    ok = await g.synth_and_play(None, ["hi"], "v", "te", cache_key="k")
    assert ok is True
    assert played["wavs"] == [b"CACHED_WAV"]   # played cached bytes
    assert synthed["n"] == 0                    # NEVER synthesized (instant)


@pytest.mark.asyncio
async def test_cache_miss_synths_and_stores(monkeypatch):
    stored = {}

    async def fake_get(key):
        return None                             # miss

    async def fake_synth(texts, voice, lang):
        return [b"FRESH_WAV"]

    async def fake_play(room, wavs, t_answer=None):
        return True

    async def fake_set(key, wavs):
        stored["key"], stored["wavs"] = key, wavs

    monkeypatch.setattr(g, "_greeting_cache_get", fake_get)
    monkeypatch.setattr(g, "synth_wavs", fake_synth)
    monkeypatch.setattr(g, "play_wavs", fake_play)
    monkeypatch.setattr(g, "_greeting_cache_set", fake_set)

    ok = await g.synth_and_play(None, ["hi"], "v", "te", cache_key="k")
    assert ok is True
    await asyncio.sleep(0)                       # let the background store run
    assert stored["key"] == "k"
    assert stored["wavs"] == [b"FRESH_WAV"]      # stored for next call


@pytest.mark.asyncio
async def test_no_cache_key_uses_live_path(monkeypatch):
    """Dynamic greeting (cache_key=None) must never read/write the cache."""
    touched = {"get": 0}

    async def fake_get(key):
        touched["get"] += 1
        return None

    monkeypatch.setattr(g, "_greeting_cache_get", fake_get)

    async def fake_play(room, items, t_answer=None):
        return True

    monkeypatch.setattr(g, "play_wavs", fake_play)

    # httpx client path — just ensure the cache was never consulted.
    await g.synth_and_play(None, [], "v", "te", cache_key=None)
    assert touched["get"] == 0

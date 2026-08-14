"""The greeting must come from the SAME engine as the conversation.

`synth_wavs` was Soniox-only, so a Cartesia deployment greeted the caller in
Soniox's Priya and then answered in a different voice — one call, two people
(Vinay heard this on the sandbox 2026-08-12).

Two halves have to hold together, and the second is the one that bites: even
with synth_wavs fixed, the Redis cache key had no provider in it, so the
already-cached Soniox audio kept being served under the same
branch/lang/voice.
"""
from __future__ import annotations

import asyncio


from agent.livekit_minimal import greeting as g
from backend.config import settings

TEXTS = ["నమస్కారం, శ్రీ స్కిన్ కేర్ క్లినిక్."]
BRANCH = "183a9c05-8f90-434b-8f9f-49fbf173aa58"


def test_cache_key_separates_providers(monkeypatch):
    monkeypatch.setattr(settings, "tts_provider", "soniox")
    soniox_key = g._greeting_cache_key(BRANCH, "te", "Priya", TEXTS)
    monkeypatch.setattr(settings, "tts_provider", "cartesia")
    cartesia_key = g._greeting_cache_key(BRANCH, "te", "Priya", TEXTS)

    assert soniox_key != cartesia_key, (
        "same key across providers — a Cartesia deployment would serve the "
        "Soniox audio already cached for this branch/lang/voice"
    )
    assert "soniox" in soniox_key and "cartesia" in cartesia_key


def test_cache_key_version_bumped_past_v1():
    """v1/v2 keys hold audio from before these fixes; must not be readable."""
    key = g._greeting_cache_key(BRANCH, "te", "Priya", TEXTS)
    assert not key.startswith("greet:v1:")
    assert not key.startswith("greet:v2:")


def test_changing_the_cartesia_voice_invalidates_the_greeting(monkeypatch):
    """Production 2026-08-12: changing the voice did not change the greeting.

    _synth_wavs_cartesia renders settings.cartesia_voice and ignores the
    Soniox-style voice_id, but the key carried only voice_id — so a new voice
    kept serving the old voice's cached audio forever.
    """
    monkeypatch.setattr(settings, "tts_provider", "cartesia")
    monkeypatch.setattr(settings, "cartesia_voice", "07bc462a-c644-49f1-baf7")
    first = g._greeting_cache_key(BRANCH, "te", "Priya", TEXTS)
    monkeypatch.setattr(settings, "cartesia_voice", "aaaaaaaa-1111-2222-3333")
    second = g._greeting_cache_key(BRANCH, "te", "Priya", TEXTS)

    assert first != second, "changing CARTESIA_VOICE did not change the key"
    assert "07bc462a-c644-49f1-baf7" in first
    assert "aaaaaaaa-1111-2222-3333" in second


def test_soniox_greetings_stay_voice_scoped(monkeypatch):
    """The Soniox path (production) must keep keying on its own voice."""
    monkeypatch.setattr(settings, "tts_provider", "soniox")
    assert (g._greeting_cache_key(BRANCH, "te", "Priya", TEXTS)
            != g._greeting_cache_key(BRANCH, "te", "Maya", TEXTS))


def test_synth_routes_to_the_configured_provider(monkeypatch):
    called: list[str] = []

    async def fake_soniox(texts, voice_id, lang_code):
        called.append("soniox"); return [b"WAV"]

    async def fake_cartesia(texts, lang_code):
        called.append("cartesia"); return [b"WAV"]

    monkeypatch.setattr(g, "_synth_wavs_soniox", fake_soniox)
    monkeypatch.setattr(g, "_synth_wavs_cartesia", fake_cartesia)

    monkeypatch.setattr(settings, "tts_provider", "cartesia")
    asyncio.run(g.synth_wavs(TEXTS, "Priya", "te"))
    monkeypatch.setattr(settings, "tts_provider", "soniox")
    asyncio.run(g.synth_wavs(TEXTS, "Priya", "te"))

    assert called == ["cartesia", "soniox"]


def test_unset_provider_still_greets_via_soniox(monkeypatch):
    """Production sets nothing explicit; it must keep its current voice."""
    called: list[str] = []

    async def fake_soniox(texts, voice_id, lang_code):
        called.append("soniox"); return [b"WAV"]

    monkeypatch.setattr(g, "_synth_wavs_soniox", fake_soniox)
    monkeypatch.setattr(settings, "tts_provider", "")
    asyncio.run(g.synth_wavs(TEXTS, "Priya", "te"))
    assert called == ["soniox"]

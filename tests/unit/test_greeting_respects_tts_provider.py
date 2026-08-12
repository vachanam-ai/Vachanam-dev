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

import pytest

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
    """v1 keys hold pre-fix Soniox audio; they must not be readable."""
    monkeypatch_free = g._greeting_cache_key(BRANCH, "te", "Priya", TEXTS)
    assert not monkeypatch_free.startswith("greet:v1:")


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

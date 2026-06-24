"""Render a clinic's welcome+greeting to audio (smallest.ai REST /tts).

Used to pre-bake Branch.welcome_audio so the call can play it INSTANTLY on
answer (no cold-TTS delay, masks the ~6s session.start). Uses the RAW smallest.ai
HTTP endpoint — NOT the livekit smallest plugin, which fails outside a job
context ("Connection error" in prewarm). Returns WAV bytes.
"""
from __future__ import annotations

import httpx

from backend.config import settings

_TTS_URL = "https://api.smallest.ai/waves/v1/tts"


def synth_wav(text: str, voice_id: str, lang_code: str = "te") -> bytes:
    """Synthesize ``text`` to WAV bytes via smallest.ai. Raises on HTTP error."""
    payload = {
        "model": settings.smallest_model,
        "voice_id": voice_id,
        "sample_rate": settings.smallest_sample_rate,
        "speed": 1,
        "language": lang_code,
        "output_format": "wav",
        "text": text,
    }
    resp = httpx.post(
        _TTS_URL,
        headers={
            "Authorization": f"Bearer {settings.smallest_api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.content

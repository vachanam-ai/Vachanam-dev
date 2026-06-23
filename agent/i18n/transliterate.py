"""Transliterate Latin person-names into the call's script so the TTS speaks
them as a NAME, not spelled letter-by-letter (RULE 6).

Bug (prod 2026-06-23): a reminder call said the doctor's name "Srinivas" as
"S… R… I… N… I…" — smallest.ai TTS, fed a Latin name inside a Telugu sentence,
reads the Latin glyphs as individual letters. The fix is to convert the name
into the target script before it ever reaches TTS.

Sarvam Transliterate API (the Sarvam key is already configured for STT). The
response field is ``transliterated_text``; ``spoken_form=True`` asks Sarvam for
the natural spoken rendering.

Best-effort (RULE 8): on ANY failure return the ORIGINAL name. A name we
couldn't transliterate is no worse than today, and a network blip must never
break an outbound greeting. Results are cached in-process (the Fly agent is
long-lived) so repeat calls for the same doctor are instant and free.
"""
from __future__ import annotations

import re

import httpx
import structlog

from backend.config import settings
from agent.i18n.languages import get_lang

logger = structlog.get_logger()

_SARVAM_URL = "https://api.sarvam.ai/transliterate"
_LATIN = re.compile(r"[A-Za-z]")
_cache: dict[tuple[str, str], str] = {}


async def spoken_name(name: str | None, lang_code: str | None) -> str:
    """Return ``name`` rendered in the call language's script for TTS.

    No-ops (returns the input unchanged) when the name is empty, has no Latin
    letters (already in an Indic script), or the call language is English.
    """
    name = (name or "").strip()
    if not name or not _LATIN.search(name):
        return name

    lang = get_lang(lang_code)
    target = lang.stt_code  # e.g. "te-IN" — Sarvam's *-IN language code
    if target == "en-IN":
        return name

    key = (name, lang.code)
    if key in _cache:
        return _cache[key]

    out = name  # RULE 8 fallback
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(
                _SARVAM_URL,
                headers={"api-subscription-key": settings.sarvam_api_key},
                json={
                    "input": name,
                    "source_language_code": "en-IN",
                    "target_language_code": target,
                    "spoken_form": True,
                },
            )
            resp.raise_for_status()
            text = (resp.json().get("transliterated_text") or "").strip()
            if text:
                out = text
    except Exception as exc:  # noqa: BLE001 — RULE 8: never break the greeting
        logger.warning("transliterate_failed", lang=lang.code, error=str(exc))

    _cache[key] = out
    return out

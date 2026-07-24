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

# Unicode block start -> Sarvam language code, for detecting the SOURCE script
# of a stored name (clinic/patient names are stored in whatever script the
# owner typed / STT produced). Marathi shares Devanagari with Hindi — hi-IN is
# an acceptable source label for transliteration purposes.
_BLOCKS: tuple[tuple[int, int, str], ...] = (
    (0x0900, 0x097F, "hi-IN"),  # Devanagari (hi/mr)
    (0x0980, 0x09FF, "bn-IN"),  # Bengali
    (0x0B80, 0x0BFF, "ta-IN"),  # Tamil
    (0x0C00, 0x0C7F, "te-IN"),  # Telugu
    (0x0C80, 0x0CFF, "kn-IN"),  # Kannada
    (0x0D00, 0x0D7F, "ml-IN"),  # Malayalam
)


def _detect_script(text: str) -> str:
    """Sarvam code of the first Indic letter found, else en-IN (Latin/other)."""
    for ch in text:
        o = ord(ch)
        for lo, hi, code in _BLOCKS:
            if lo <= o <= hi:
                return code
    return "en-IN"


async def _sarvam_hop(text: str, src: str, tgt: str) -> str | None:
    """One Sarvam transliteration hop, or None on failure."""
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(
                _SARVAM_URL,
                headers={"api-subscription-key": settings.sarvam_api_key},
                json={
                    "input": text,
                    "source_language_code": src,
                    "target_language_code": tgt,
                    "spoken_form": True,
                },
            )
            resp.raise_for_status()
            out = (resp.json().get("transliterated_text") or "").strip()
            return out or None
    except Exception as exc:  # noqa: BLE001 — RULE 8
        logger.warning("transliterate_hop_failed", src=src, tgt=tgt, error=str(exc))
        return None


async def spoken_text(text: str | None, lang_code: str | None) -> str:
    """Render a stored name (clinic/patient/doctor) in the CALL language's
    script so the TTS pronounces it instead of mangling foreign glyphs.

    Live bug (2026-07-03): the English agent greeted "I'm the AI assistant
    from శ్రీ వెంకటేశ్వర" — the en TTS garbled the Telugu glyphs ("clinic name
    spelled very wrongly"). Sarvam supports Latin<->Indic only, so Indic→Indic
    goes via a Latin hop. Best-effort with cache; any failure returns the
    original text (RULE 8)."""
    text = (text or "").strip()
    if not text:
        return text
    lang = get_lang(lang_code)
    src = _detect_script(text)
    tgt = lang.stt_code
    if src == tgt or (src == "hi-IN" and tgt == "mr-IN"):
        return text  # already in the call's script (mr shares Devanagari)

    key = (text, f"{src}>{tgt}")
    if key in _cache:
        return _cache[key]

    if src == "en-IN" or tgt == "en-IN":
        out = await _sarvam_hop(text, src, tgt)
    else:
        # Indic -> Indic: Sarvam refuses direct, hop through Latin.
        latin = await _sarvam_hop(text, src, "en-IN")
        out = await _sarvam_hop(latin, "en-IN", tgt) if latin else None

    result = out or text
    _cache[key] = result
    return result


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

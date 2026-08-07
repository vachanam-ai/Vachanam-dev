"""Transliterate Latin person-names into the call's script so the TTS speaks
them as a NAME, not spelled letter-by-letter (RULE 6).

Bug (prod 2026-06-23): a reminder call said the doctor's name "Srinivas" as
"S… R… I… N… I…" — TTS, fed a Latin name inside a Telugu sentence,
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


# ── offline, script-independent name matching ────────────────────────────────
# Vinay 2026-08-07, live E2E in Telugu: the patient asked for "శ్రీనివాస్" and
# the clinic answered "we don't have a doctor named Srinivas" — the roster
# stores Latin names, and wa_agent's matcher stripped every non-Latin character
# before comparing, so a Telugu-script name became an EMPTY token set. Any
# patient naming their doctor in their own script could not book at all, which
# on a Telugu-first product is the whole flow.
#
# Deliberately OFFLINE and deterministic, unlike spoken_name() above: matching
# runs on every message, must not depend on the Sarvam key being set, and must
# never add a network hop to a lookup. #478 reverted offline transliteration
# for SPEAKING names (mechanical mapping mangles proper nouns) — that objection
# does not apply here, because this output is never spoken or shown. It exists
# only to be compared.
#
# Every Indic block below follows the same ISCII-derived ordering, so ONE table
# indexed by (codepoint - block_start) serves Telugu, Devanagari, Tamil,
# Kannada, Malayalam, Bengali and Gujarati alike.

_INDIC_BLOCKS: tuple[tuple[int, int], ...] = (
    (0x0900, 0x097F),  # Devanagari (hi, mr)
    (0x0980, 0x09FF),  # Bengali
    (0x0A80, 0x0AFF),  # Gujarati
    (0x0B80, 0x0BFF),  # Tamil
    (0x0C00, 0x0C7F),  # Telugu
    (0x0C80, 0x0CFF),  # Kannada
    (0x0D00, 0x0D7F),  # Malayalam
)

# Consonant offsets 0x15..0x39, already folded into coarse phonetic CLASSES:
# aspirates collapse onto their plain form (kha->k), retroflex onto dental
# (Ta->t), and all three sibilants onto s. That folding is what makes
# "శ్రీనివాస్" and "Srinivas" compare equal despite spelling apart.
_CONSONANTS = {
    0x15: "k", 0x16: "k", 0x17: "g", 0x18: "g", 0x19: "n",
    0x1A: "c", 0x1B: "c", 0x1C: "j", 0x1D: "j", 0x1E: "n",
    0x1F: "t", 0x20: "t", 0x21: "d", 0x22: "d", 0x23: "n",
    0x24: "t", 0x25: "t", 0x26: "d", 0x27: "d", 0x28: "n", 0x29: "n",
    0x2A: "p", 0x2B: "p", 0x2C: "b", 0x2D: "b", 0x2E: "m",
    0x2F: "y", 0x30: "r", 0x31: "r", 0x32: "l", 0x33: "l", 0x34: "l",
    0x35: "v", 0x36: "s", 0x37: "s", 0x38: "s", 0x39: "h",
}

_LATIN_FOLD = str.maketrans({"c": "k", "w": "v", "f": "p", "z": "j", "q": "k"})
_VOWELS = set("aeiou")


def consonant_skeleton(text: str | None) -> str:
    """A script-independent consonant fingerprint of a name.

    "Srinivas", "శ్రీనివాస్" and "श्रीनिवास" all reduce to "srnvs", so a name
    can be matched across scripts without a network call. Vowels are dropped
    entirely: they are exactly where transliteration and STT disagree most
    (long vs short, "ee" vs "i"), and they carry the least identifying signal.
    """
    if not text:
        return ""
    out: list[str] = []
    for ch in text:
        o = ord(ch)
        mapped = None
        for start, end in _INDIC_BLOCKS:
            if start <= o <= end:
                mapped = _CONSONANTS.get(o - start, "")  # vowels/signs -> ""
                break
        if mapped is not None:
            out.append(mapped)
        elif ch.isascii() and ch.isalpha():
            out.append(ch.lower())
    skeleton = "".join(out).translate(_LATIN_FOLD)
    # Drop vowels, then aspiration ('bh' -> 'b'), then collapse doubles so
    # "Lakshmi"/"లక్ష్మి" and "Sunitha"/"Sunita" cannot disagree.
    skeleton = "".join(c for c in skeleton if c not in _VOWELS)
    skeleton = "".join(
        c for i, c in enumerate(skeleton) if c != "h" or i == 0
    )
    squeezed: list[str] = []
    for c in skeleton:
        if not squeezed or squeezed[-1] != c:
            squeezed.append(c)
    return "".join(squeezed)

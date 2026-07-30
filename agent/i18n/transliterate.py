"""Offline transliteration between Indic scripts and Latin.

Replaces the Sarvam Transliterate API (removed 2026-07-30 with the rest of
Sarvam — Soniox is now the sole speech provider). indic-transliteration is a
deterministic offline library: no API key, no network hop, no per-call cost,
and it converts Indic→Indic DIRECTLY (Sarvam needed a Latin hop).

Two jobs:
  1. Indic → Latin ROMANIZATION for cross-script NAME MATCHING (booking
     identity #467, doctor-name resolution #294). ISO-15919 then stripped to
     ASCII. The residual spelling gap between the ISO scheme and how a name is
     typed in English (ś/sh/s, v/w, aspiration h, doubled letters) is absorbed
     by phonetic_fold() at comparison time — see agent/tools/booking_tools.py.
  2. Latin/Indic → CALL-SCRIPT rendering so TTS PRONOUNCES a name instead of
     spelling Latin glyphs letter-by-letter (RULE 6, prod bug 2026-06-23).
     English spellings don't follow a transliteration scheme, so Latin→Indic is
     approximate but speakable — far better than letter-spelling. (Validate on a
     real call; Soniox TTS handles the residual.)

Best-effort everywhere (RULE 8): ANY failure returns the ORIGINAL text — a name
we couldn't convert is no worse than before, and a library hiccup must never
break a greeting or a booking. Cached in-process (the Fly agent is long-lived).
"""
from __future__ import annotations

import re
import unicodedata

import structlog
from indic_transliteration import sanscript
from indic_transliteration.sanscript import transliterate as _sanscript

from agent.i18n.languages import get_lang

logger = structlog.get_logger()

_LATIN = re.compile(r"[A-Za-z]")
_cache: dict[tuple[str, str], str] = {}

# _detect_script code (*-IN) → indic-transliteration scheme. Marathi shares
# Devanagari with Hindi, so hi-IN/mr-IN both map to DEVANAGARI.
_SCHEME: dict[str, str] = {
    "hi-IN": sanscript.DEVANAGARI,
    "mr-IN": sanscript.DEVANAGARI,
    "bn-IN": sanscript.BENGALI,
    "ta-IN": sanscript.TAMIL,
    "te-IN": sanscript.TELUGU,
    "kn-IN": sanscript.KANNADA,
    "ml-IN": sanscript.MALAYALAM,
}
# ITRANS parses casual Latin input for the (approximate) English→Indic direction.
_LATIN_INPUT = sanscript.ITRANS

# Unicode block start → detect code, for the SOURCE script of a stored name
# (names are stored in whatever script the owner typed / STT produced).
_BLOCKS: tuple[tuple[int, int, str], ...] = (
    (0x0900, 0x097F, "hi-IN"),  # Devanagari (hi/mr)
    (0x0980, 0x09FF, "bn-IN"),  # Bengali
    (0x0B80, 0x0BFF, "ta-IN"),  # Tamil
    (0x0C00, 0x0C7F, "te-IN"),  # Telugu
    (0x0C80, 0x0CFF, "kn-IN"),  # Kannada
    (0x0D00, 0x0D7F, "ml-IN"),  # Malayalam
)


def _detect_script(text: str) -> str:
    """Detect code of the first Indic letter found, else en-IN (Latin/other)."""
    for ch in text or "":
        o = ord(ch)
        for lo, hi, code in _BLOCKS:
            if lo <= o <= hi:
                return code
    return "en-IN"


def _strip_diacritics(text: str) -> str:
    """NFKD-decompose and drop combining marks: ISO 'śrīnivās' → 'srinivas'."""
    return "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )


def phonetic_fold(s: str) -> str:
    """Collapse a romanized name to a spelling-insensitive key for fuzzy
    cross-script matching (booking identity / doctor lookup). Deliberately
    LOSSY — it errs toward matching so a legitimate caller is never locked out
    of cancel/reschedule (#467; phone is the primary factor, this is a second
    factor). NOT for display.

      - lowercase, strip diacritics (ś→s, ṇ→n, ā→a)
      - w → v            (English 'Venkateswara' vs ISO 'v')
      - drop 'h' after a consonant (aspiration/sibilant noise: sh→s, ksh→ks,
        th→t) — leaves a leading/standalone 'h' ('Hari') intact
      - collapse doubled letters (Reddyy→redy), keep [a-z ] only
    """
    s = _strip_diacritics((s or "").lower())
    s = s.replace("w", "v")
    s = re.sub(r"(?<=[bcdgjkpqstz])h", "", s)
    s = re.sub(r"[^a-z ]", " ", s)
    s = re.sub(r"(.)\1+", r"\1", s)
    return " ".join(s.split())


def romanize(text: str | None, src: str | None = None) -> str:
    """Indic → ASCII Latin (ISO-15919, diacritics stripped). A Latin/empty input
    returns unchanged. Best-effort: returns the input on any failure (RULE 8)."""
    t = (text or "").strip()
    if not t:
        return ""
    src = src or _detect_script(t)
    if src == "en-IN":
        return t
    scheme = _SCHEME.get(src)
    if scheme is None:
        return t
    try:
        return _strip_diacritics(_sanscript(t, scheme, sanscript.ISO)).strip() or t
    except Exception as exc:  # noqa: BLE001 — RULE 8
        logger.warning("romanize_failed", src=src, error=str(exc))
        return t


def _convert(text: str, src: str, tgt: str) -> str:
    """One transliteration hop src→tgt (both *-IN codes). Returns input on
    failure (RULE 8)."""
    if src == tgt:
        return text
    if tgt == "en-IN":
        return romanize(text, src)
    try:
        src_scheme = _LATIN_INPUT if src == "en-IN" else _SCHEME.get(src)
        tgt_scheme = _SCHEME.get(tgt)
        if src_scheme is None or tgt_scheme is None:
            return text
        src_in = text.lower() if src == "en-IN" else text
        return _sanscript(src_in, src_scheme, tgt_scheme).strip() or text
    except Exception as exc:  # noqa: BLE001 — RULE 8
        logger.warning("transliterate_failed", src=src, tgt=tgt, error=str(exc))
        return text


async def spoken_text(text: str | None, lang_code: str | None) -> str:
    """Render a stored name (clinic/patient/doctor) in the CALL language's
    script so TTS pronounces it, or to ASCII Latin (lang 'en') so it can be
    matched against Latin DB names. No-op when already in the target script.
    Best-effort with cache; any failure returns the original (RULE 8)."""
    text = (text or "").strip()
    if not text:
        return text
    tgt = get_lang(lang_code).stt_code
    src = _detect_script(text)
    if src == tgt or (src == "hi-IN" and tgt == "mr-IN"):
        return text  # already in the call's script (mr shares Devanagari)

    key = (text, f"{src}>{tgt}")
    if key in _cache:
        return _cache[key]
    result = _convert(text, src, tgt)
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
    tgt = get_lang(lang_code).stt_code
    if tgt == "en-IN":
        return name
    key = (name, tgt)
    if key in _cache:
        return _cache[key]
    result = _convert(name, "en-IN", tgt)
    _cache[key] = result
    return result

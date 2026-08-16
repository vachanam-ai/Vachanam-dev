"""Deterministic storage normalization for patient identity fields."""
from __future__ import annotations

import re
import unicodedata

from indic_transliteration import sanscript

_SCRIPT_SCHEMES = (
    (0x0900, 0x097F, sanscript.DEVANAGARI),
    (0x0980, 0x09FF, sanscript.BENGALI),
    (0x0A00, 0x0A7F, sanscript.GURMUKHI),
    (0x0A80, 0x0AFF, sanscript.GUJARATI),
    (0x0B00, 0x0B7F, sanscript.ORIYA),
    (0x0B80, 0x0BFF, sanscript.TAMIL),
    (0x0C00, 0x0C7F, sanscript.TELUGU),
    (0x0C80, 0x0CFF, sanscript.KANNADA),
    (0x0D00, 0x0D7F, sanscript.MALAYALAM),
)


def _scheme(character: str) -> str | None:
    point = ord(character)
    return next(
        (scheme for start, end, scheme in _SCRIPT_SCHEMES if start <= point <= end),
        None,
    )


def _latinize_run(text: str, scheme: str) -> str:
    value = sanscript.transliterate(text, scheme, sanscript.ITRANS).lower()
    for source, target in (
        ("rr^i", "ri"), ("l^i", "li"), (".n", "n"), (".m", "m"),
        ("~n", "n"), ("^", ""),
    ):
        value = value.replace(source, target)
    return re.sub(r"[^a-z'-]+", " ", value)


def normalize_patient_name(value: str | None) -> str:
    """Return one clean Latin-script display name or raise ``ValueError``.

    Transliteration is local and deterministic, so a provider outage can never
    reintroduce Indic-script names or delay an appointment confirmation.
    """
    text = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value or "")).strip()
    if not text:
        raise ValueError("patient name is required")

    pieces: list[str] = []
    run: list[str] = []
    run_scheme: str | None = None

    def flush() -> None:
        nonlocal run, run_scheme
        if run:
            raw = "".join(run)
            pieces.append(_latinize_run(raw, run_scheme) if run_scheme else raw)
        run, run_scheme = [], None

    for character in text:
        scheme = _scheme(character)
        if scheme != run_scheme and (scheme is not None or run_scheme is not None):
            flush()
        run.append(character)
        run_scheme = scheme
    flush()

    normalized = re.sub(r"\s+", " ", "".join(pieces)).strip(" .'-")
    if not normalized or any(ch.isalpha() and not ch.isascii() for ch in normalized):
        raise ValueError("patient name must use English letters")
    if len(normalized) > 255:
        raise ValueError("patient name is too long")
    if normalized != text:
        normalized = " ".join(part.capitalize() for part in normalized.split())
    return normalized


def normalize_patient_age(value: int | str | None) -> int | None:
    """Normalize Unicode digits to an integer without ever inferring an age."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError("patient age must be a whole number")
    text = unicodedata.normalize("NFKC", str(value)).strip()
    if not text.isdecimal():
        raise ValueError("patient age must be a whole number")
    age = int(text)
    if not 0 <= age <= 120:
        raise ValueError("patient age must be between 0 and 120")
    return age

"""De-identification gate for the humanizer example bank (DPDP / RULE 9 / RULE 1).

The example bank stores ONLY de-identified conversational patterns — never a
patient's personal data. This is the hard precondition on every bank write:
`assert_deidentified(text)` raises if the text carries directly-identifying data
(phone, email, age, long digit runs like OTPs/IDs). Personal names must already
be placeholders ({name}); reliable name detection in Telugu script is not
attempted here, so the bank's WRITE CONTRACT requires names be templated before
they reach the gate — the gate is the safety net for the identifiers we CAN
detect deterministically.

If anything is found, the write is REJECTED (fail loud) — we never silently
store PII. `scrub()` is provided for callers that want to template a line first.
"""
from __future__ import annotations

import re

# Indian mobile, optionally +91/91/0 prefixed, possibly spaced/hyphenated.
_PHONE = re.compile(r"(?:\+?91[\s-]?|0)?[6-9]\d{2}[\s-]?\d{3}[\s-]?\d{4}\b")
# Any run of 5+ digits — phones, OTPs, IDs, MRNs. (Spoken times use {time}; a
# literal "10:30" has no 5-digit run, so it passes.)
_LONG_DIGITS = re.compile(r"\d{5,}")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
# Age: a small number next to an age word, in EITHER order (English "45 years",
# Telugu "వయసు 60"), English or Telugu word.
_AGE = re.compile(
    r"\b\d{1,3}\s*(?:years?|yrs?|year[\s-]?old|ఏళ్ల|ఏళ్ళ|సంవత్సర|వయసు)"
    r"|(?:age|వయసు|ఏళ్ల|ఏళ్ళ)\s*\d{1,3}",
    re.IGNORECASE,
)


class DeidentificationError(ValueError):
    """Raised when text destined for the example bank carries identifying data."""


def find_pii(text: str) -> list[str]:
    """Return a list of PII kinds found in ``text`` (empty = clean)."""
    text = text or ""
    found: list[str] = []
    if _PHONE.search(text):
        found.append("phone")
    if _EMAIL.search(text):
        found.append("email")
    if _AGE.search(text):
        found.append("age")
    if _LONG_DIGITS.search(text):
        found.append("long_digits")
    return found


def assert_deidentified(text: str) -> None:
    """Raise DeidentificationError if ``text`` carries identifying data.

    The hard gate for every example-bank write — DPDP RULE 1 / RULE 9.
    """
    kinds = find_pii(text)
    if kinds:
        raise DeidentificationError(
            f"refusing to store identifying data: {', '.join(sorted(set(kinds)))}"
        )


def scrub(text: str) -> str:
    """Best-effort: replace detectable identifiers with placeholders. For
    callers that template a raw turn before storing; the gate still runs after."""
    text = _PHONE.sub("{phone}", text or "")
    text = _EMAIL.sub("{email}", text)
    text = _AGE.sub("{age}", text)
    text = _LONG_DIGITS.sub("{number}", text)
    return text

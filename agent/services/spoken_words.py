"""Deterministic word substitutions at the TTS boundary.

Two rules Vinay set on 2026-08-06, both about what the caller HEARS:

1. WEEKDAYS ARE ALWAYS ENGLISH, in every language. "Saturday", never
   "శనివారం" / "शनिवार". Clinic patients say the English day names, and the
   agent switching to a native day name mid-sentence reads as a different day.

2. IN AN ENGLISH CALL, NUMBERS ARE ENGLISH. After a mid-call switch to English
   the model kept writing Telugu number WORDS, so "10am" came out of the TTS as
   "padi am" (పది = ten). tts_sanitizer already forces DIGITS to English words
   and its own comment concedes the gap: "Native-language number WORDS the
   model writes can't be caught here". This module closes exactly that gap.

WHY HERE AND NOT IN THE PROMPT. Both were prompt rules already and the model
still broke them on live calls (the same reason #408 moved digits to a
deterministic conversion). A rule that must hold every time belongs at the
boundary, not in an instruction the model may or may not follow.

HOW IT REACHES THE AUDIO. The map is merged into the pronunciation replacer
(agent/services/pronunciation.build_replacer), which is already a
streaming-safe substitution with a prefix hold, so a word split across two LLM
chunks is still matched. Nothing new runs on the turn hot path.

SCOPE. Weekdays cover all seven non-English call languages. Number words are
converted ONLY when the call language is English (in a Telugu call, Telugu
number words are correct and desired) and cover Telugu + Hindi, the two
languages a caller actually switches to English FROM.
"""
from __future__ import annotations

from agent.services.telugu_dates import MONTHS_TE, telugu_number
from agent.services.tts_sanitizer import _cardinal

# ── Rule 1: weekday names, every language → English ──────────────────────────
# Longest forms first matters only for readability here; build_replacer sorts
# by length itself, so "ஞாயிற்றுக்கிழமை" wins over "ஞாயிறு".
WEEKDAYS_TO_ENGLISH: dict[str, str] = {
    # Telugu
    "ఆదివారం": "Sunday", "సోమవారం": "Monday", "మంగళవారం": "Tuesday",
    "బుధవారం": "Wednesday", "గురువారం": "Thursday", "శుక్రవారం": "Friday",
    "శనివారం": "Saturday",
    # Hindi
    "रविवार": "Sunday", "इतवार": "Sunday", "सोमवार": "Monday",
    "मंगलवार": "Tuesday", "बुधवार": "Wednesday", "गुरुवार": "Thursday",
    "बृहस्पतिवार": "Thursday", "शुक्रवार": "Friday", "शनिवार": "Saturday",
    # Marathi (shares Devanagari; मंगळवार differs from Hindi)
    "मंगळवार": "Tuesday",
    # Tamil — both the bare and the -கிழமை forms
    "ஞாயிற்றுக்கிழமை": "Sunday", "ஞாயிறு": "Sunday",
    "திங்கட்கிழமை": "Monday", "திங்கள்": "Monday",
    "செவ்வாய்க்கிழமை": "Tuesday", "செவ்வாய்": "Tuesday",
    "புதன்கிழமை": "Wednesday", "புதன்": "Wednesday",
    "வியாழக்கிழமை": "Thursday", "வியாழன்": "Thursday",
    "வெள்ளிக்கிழமை": "Friday", "வெள்ளி": "Friday",
    "சனிக்கிழமை": "Saturday", "சனி": "Saturday",
    # Kannada
    "ಭಾನುವಾರ": "Sunday", "ಸೋಮವಾರ": "Monday", "ಮಂಗಳವಾರ": "Tuesday",
    "ಬುಧವಾರ": "Wednesday", "ಗುರುವಾರ": "Thursday", "ಶುಕ್ರವಾರ": "Friday",
    "ಶನಿವಾರ": "Saturday",
    # Bengali
    "রবিবার": "Sunday", "সোমবার": "Monday", "মঙ্গলবার": "Tuesday",
    "বুধবার": "Wednesday", "বৃহস্পতিবার": "Thursday", "শুক্রবার": "Friday",
    "শনিবার": "Saturday",
    # Malayalam
    "ഞായറാഴ്ച": "Sunday", "തിങ്കളാഴ്ച": "Monday", "ചൊവ്വാഴ്ച": "Tuesday",
    "ബുധനാഴ്ച": "Wednesday", "വ്യാഴാഴ്ച": "Thursday", "വെള്ളിയാഴ്ച": "Friday",
    "ശനിയാഴ്ച": "Saturday",
}

# ── Rule 2: native number words → English, for ENGLISH calls only ────────────
# Telugu numbers are generated from the SAME function that produces them
# (telugu_dates.telugu_number), so this reverse map can never drift out of sync
# with the words the deterministic confirmation speech emits.
_HINDI_NUMBERS: dict[str, int] = {
    "एक": 1, "दो": 2, "तीन": 3, "चार": 4, "पाँच": 5, "पांच": 5, "छह": 6,
    "छः": 6, "सात": 7, "आठ": 8, "नौ": 9, "दस": 10, "ग्यारह": 11, "बारह": 12,
    "तेरह": 13, "चौदह": 14, "पंद्रह": 15, "बीस": 20, "तीस": 30, "चालीस": 40,
    "पैंतालीस": 45, "पचास": 50,
}

# Day-part and o'clock words: in an English call these must not be spoken at
# all. They carry no information English does not already carry via A.M./P.M.,
# so they are dropped rather than translated ("ఉదయం 10" -> "10").
_DAYPART_DROP = (
    "ఉదయం", "పొద్దున్నే", "పొద్దున", "మధ్యాహ్నం", "సాయంత్రం", "రాత్రి",
    "గంటలకి", "గంటలకు", "గంటలక", "గంటకి", "గంటలు", "గంటల",
    "सुबह", "दोपहर", "शाम", "रात", "बजे",
)


def _english_number_words() -> dict[str, str]:
    """{native number word: english number word} for an English call."""
    out: dict[str, str] = {}
    for n in range(1, 60):
        te = telugu_number(n)
        # telugu_number falls back to str(n) outside 1-99; skip anything that
        # did not actually produce a word, and skip the empty 0 entry.
        if te and not te.isdigit():
            out[te] = _cardinal(n)
        # "X-and-a-half" half-hour form used by telugu_time (పదిన్నర = 10:30).
        if 1 <= n <= 12 and te and not te.isdigit():
            out[f"{te}న్నర"] = f"{_cardinal(n)} thirty"
    for hi, n in _HINDI_NUMBERS.items():
        out[hi] = _cardinal(n)
    for month_index, te_month in enumerate(MONTHS_TE, start=1):
        out[te_month] = [
            "January", "February", "March", "April", "May", "June", "July",
            "August", "September", "October", "November", "December",
        ][month_index - 1]
    for word in _DAYPART_DROP:
        out[word] = ""
    return out


NUMBER_WORDS_TO_ENGLISH: dict[str, str] = _english_number_words()


def speech_map(lang_code: str | None) -> dict[str, str]:
    """Deterministic TTS-boundary substitutions for a call in LANG_CODE.

    Weekdays always. Number words only for an English call — a Telugu call
    SHOULD say "పది గంటలకి", and rewriting that to English would be the bug,
    not the fix.
    """
    mapping = dict(WEEKDAYS_TO_ENGLISH)
    if (lang_code or "").lower().startswith("en"):
        mapping.update(NUMBER_WORDS_TO_ENGLISH)
    return mapping

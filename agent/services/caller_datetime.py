"""Conservative, deterministic date/time receipts from a caller utterance."""

from __future__ import annotations

from datetime import date, timedelta
import re
import unicodedata


_NUMBER_WORDS: dict[str, dict[str, int]] = {
    "en": {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
        "eleven": 11,
        "twelve": 12,
        "thirteen": 13,
        "fourteen": 14,
        "sixteen": 16,
        "seventeen": 17,
        "eighteen": 18,
        "nineteen": 19,
        "twenty": 20,
        "twenty one": 21,
        "twenty-one": 21,
        "twenty two": 22,
        "twenty-two": 22,
        "twenty three": 23,
        "twenty-three": 23,
        "fifteen": 15,
        "thirty": 30,
        "forty five": 45,
        "forty-five": 45,
    },
    "te": {
        "ఒకటి": 1,
        "ఒంటి": 1,
        "రెండు": 2,
        "మూడు": 3,
        "నాలుగు": 4,
        "ఐదు": 5,
        "ఆరు": 6,
        "ఏడు": 7,
        "ఎనిమిది": 8,
        "తొమ్మిది": 9,
        "పది": 10,
        "పదకొండు": 11,
        "పన్నెండు": 12,
        "పదిహేను": 15,
        "ముప్పై": 30,
        "నలభై ఐదు": 45,
    },
    "hi": {
        "एक": 1,
        "दो": 2,
        "तीन": 3,
        "चार": 4,
        "पाँच": 5,
        "पांच": 5,
        "छह": 6,
        "छः": 6,
        "सात": 7,
        "आठ": 8,
        "नौ": 9,
        "दस": 10,
        "ग्यारह": 11,
        "बारह": 12,
        "पंद्रह": 15,
        "तीस": 30,
        "पैंतालीस": 45,
    },
    "ta": {
        "ஒன்று": 1,
        "இரண்டு": 2,
        "மூன்று": 3,
        "நான்கு": 4,
        "ஐந்து": 5,
        "ஆறு": 6,
        "ஏழு": 7,
        "எட்டு": 8,
        "ஒன்பது": 9,
        "பத்து": 10,
        "பதினொன்று": 11,
        "பன்னிரண்டு": 12,
        "பதினைந்து": 15,
        "முப்பது": 30,
        "நாற்பத்தைந்து": 45,
    },
    "kn": {
        "ಒಂದು": 1,
        "ಎರಡು": 2,
        "ಮೂರು": 3,
        "ನಾಲ್ಕು": 4,
        "ಐದು": 5,
        "ಆರು": 6,
        "ಏಳು": 7,
        "ಎಂಟು": 8,
        "ಒಂಬತ್ತು": 9,
        "ಹತ್ತು": 10,
        "ಹನ್ನೊಂದು": 11,
        "ಹನ್ನೆರಡು": 12,
        "ಹದಿನೈದು": 15,
        "ಮೂವತ್ತು": 30,
        "ನಲವತ್ತೈದು": 45,
    },
    "ml": {
        "ഒന്ന്": 1,
        "ഒരു": 1,
        "രണ്ട്": 2,
        "മൂന്ന്": 3,
        "നാല്": 4,
        "അഞ്ച്": 5,
        "ആറ്": 6,
        "ഏഴ്": 7,
        "എട്ട്": 8,
        "ഒമ്പത്": 9,
        "പത്ത്": 10,
        "പതിനൊന്ന്": 11,
        "പന്ത്രണ്ട്": 12,
        "പതിനഞ്ച്": 15,
        "മുപ്പത്": 30,
        "നാൽപ്പത്തിയഞ്ച്": 45,
    },
    "mr": {
        "एक": 1,
        "दोन": 2,
        "तीन": 3,
        "चार": 4,
        "पाच": 5,
        "सहा": 6,
        "सात": 7,
        "आठ": 8,
        "नऊ": 9,
        "दहा": 10,
        "अकरा": 11,
        "बारा": 12,
        "पंधरा": 15,
        "तीस": 30,
        "पंचेचाळीस": 45,
    },
    "bn": {
        "এক": 1,
        "দুই": 2,
        "তিন": 3,
        "চার": 4,
        "পাঁচ": 5,
        "ছয়": 6,
        "ছয়": 6,
        "সাত": 7,
        "আট": 8,
        "নয়": 9,
        "নয়": 9,
        "দশ": 10,
        "এগারো": 11,
        "বারো": 12,
        "পনেরো": 15,
        "ত্রিশ": 30,
        "পঁয়তাল্লিশ": 45,
        "পয়তাল্লিশ": 45,
    },
}

_DAYPARTS = {
    "en": ({"morning"}, {"afternoon", "evening", "tonight", "night"}),
    "te": ({"ఉదయం", "పొద్దున"}, {"మధ్యాహ్నం", "సాయంత్రం", "రాత్రి"}),
    "hi": ({"सुबह", "सवेरे"}, {"दोपहर", "शाम", "रात"}),
    "ta": ({"காலை"}, {"மதியம்", "மாலை", "சாயங்காலம்", "இரவு"}),
    "kn": ({"ಬೆಳಗ್ಗೆ", "ಮುಂಜಾನೆ"}, {"ಮಧ್ಯಾಹ್ನ", "ಸಂಜೆ", "ರಾತ್ರಿ"}),
    "ml": ({"രാവിലെ"}, {"ഉച്ചയ്ക്ക്", "വൈകുന്നേരം", "സന്ധ്യയ്ക്ക്", "രാത്രി"}),
    "mr": ({"सकाळी"}, {"दुपारी", "संध्याकाळी", "रात्री"}),
    "bn": ({"সকাল", "সকালে"}, {"দুপুরে", "বিকেলে", "সন্ধ্যায়", "রাতে"}),
}

_CLOCK_SUFFIX = {
    "en": r"o['’]?clock",
    "te": r"గంట(?:కి|లకు|లు|ల)?",
    "hi": r"बजे",
    "ta": r"மணி(?:க்கு)?",
    "kn": r"ಗಂಟೆ(?:ಗೆ)?",
    "ml": r"മണി(?:ക്ക്)?",
    "mr": r"वाजता",
    "bn": r"টা(?:য়|য়)?",
}

_MINUTE_CONNECTOR = {
    "en": r"\s+",
    "te": r"\s*(?:గంట(?:ల|లు|కి|లకు)?\s*)?",
    "hi": r"\s*(?:(?:बजकर|बजे)\s*)?",
    "ta": r"\s*(?:மணி(?:க்கு)?\s*)?",
    "kn": r"\s*(?:ಗಂಟೆ(?:ಗೆ)?\s*)?",
    "ml": r"\s*(?:മണി(?:ക്ക്)?\s*)?",
    "mr": r"\s*(?:(?:वाजून|वाजता)\s*)?",
    "bn": r"\s*(?:টা(?:য়|য়)?\s*)?",
}

_MINUTE_UNIT = {
    "en": r"(?:\s+minutes?)?",
    "te": r"(?:\s*నిమిషా(?:లు|లకి)?)?",
    "hi": r"(?:\s*मिनट)?",
    "ta": r"(?:\s*நிமிடம்)?",
    "kn": r"(?:\s*ನಿಮಿಷ)?",
    "ml": r"(?:\s*മിനിറ്റ്)?",
    "mr": r"(?:\s*मिनिट(?:ांनी)?)?",
    "bn": r"(?:\s*মিনিট)?",
}

_FRACTIONS: dict[str, dict[str, tuple[int, int]]] = {
    "te": {"ఐదున్నర": (5, 30), "పావుతక్కువ ఆరు": (5, 45), "పావు తక్కువ ఆరు": (5, 45)},
    "hi": {"साढ़े पाँच": (5, 30), "साढ़े पांच": (5, 30), "सवा पाँच": (5, 15), "पौने छह": (5, 45)},
    "ta": {"ஐந்தரை": (5, 30), "ஐந்தேகால்": (5, 15), "ஐந்தேமுக்கால்": (5, 45)},
    "kn": {"ಐದುವರೆ": (5, 30), "ಐದುಕಾಲು": (5, 15), "ಕಾಲು ಕಡಿಮೆ ಆರು": (5, 45)},
    "ml": {"അഞ്ചര": (5, 30), "അഞ്ചേകാൽ": (5, 15), "അഞ്ചേമുക്കാൽ": (5, 45)},
    "mr": {"साडेपाच": (5, 30), "सव्वापाच": (5, 15), "पावणेसहा": (5, 45)},
    "bn": {"সাড়ে পাঁচটা": (5, 30), "সোয়া পাঁচটা": (5, 15), "পৌনে ছয়টা": (5, 45)},
}

_RELATIVE_DATES = {
    "en": {"today": 0, "tomorrow": 1, "day after tomorrow": 2},
    "te": {"ఈరోజు": 0, "ఇవాళ": 0, "రేపు": 1, "ఎల్లుండి": 2},
    "hi": {"आज": 0, "कल": 1, "परसों": 2},
    "ta": {"இன்று": 0, "இன்னைக்கு": 0, "நாளை": 1, "நாளைக்கு": 1, "நாளை மறுநாள்": 2, "நாளன்னைக்கு": 2},
    "kn": {"ಇಂದು": 0, "ಇವತ್ತು": 0, "ನಾಳೆ": 1, "ನಾಡಿದ್ದು": 2},
    "ml": {"ഇന്ന്": 0, "നാളെ": 1, "മറ്റന്നാൾ": 2},
    "mr": {"आज": 0, "उद्या": 1, "परवा": 2},
    "bn": {"আজ": 0, "আগামীকাল": 1, "কাল": 1, "পরশু": 2},
}

_WEEKDAYS = {
    "en": ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"),
    "te": ("సోమవారం", "మంగళవారం", "బుధవారం", "గురువారం", "శుక్రవారం", "శనివారం", "ఆదివారం"),
    "hi": ("सोमवार", "मंगलवार", "बुधवार", "गुरुवार", "शुक्रवार", "शनिवार", "रविवार"),
    "ta": ("திங்கள்", "செவ்வாய்", "புதன்", "வியாழன்", "வெள்ளி", "சனி", "ஞாயிறு"),
    "kn": ("ಸೋಮವಾರ", "ಮಂಗಳವಾರ", "ಬುಧವಾರ", "ಗುರುವಾರ", "ಶುಕ್ರವಾರ", "ಶನಿವಾರ", "ಭಾನುವಾರ"),
    "ml": ("തിങ്കളാഴ്ച", "ചൊവ്വാഴ്ച", "ബുധനാഴ്ച", "വ്യാഴാഴ്ച", "വെള്ളിയാഴ്ച", "ശനിയാഴ്ച", "ഞായറാഴ്ച"),
    "mr": ("सोमवार", "मंगळवार", "बुधवार", "गुरुवार", "शुक्रवार", "शनिवार", "रविवार"),
    "bn": ("সোমবার", "মঙ্গলবার", "বুধবার", "বৃহস্পতিবার", "শুক্রবার", "শনিবার", "রবিবার"),
}

_LONG_WEEKDAYS = {
    "ta": {
        "திங்கட்கிழமை": 0,
        "செவ்வாய்க்கிழமை": 1,
        "புதன்கிழமை": 2,
        "வியாழக்கிழமை": 3,
        "வெள்ளிக்கிழமை": 4,
        "சனிக்கிழமை": 5,
        "ஞாயிற்றுக்கிழமை": 6,
    },
    "hi": {"इतवार": 6, "बृहस्पतिवार": 3},
}

_MONTHS = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sept": 9,
    "sep": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}
_MONTH_PATTERN = "|".join(re.escape(value) for value in sorted(_MONTHS, key=len, reverse=True))

_CLOCK_RE = re.compile(
    r"(?<!\d)(?P<hour>[01]?\d|2[0-3])"
    r"(?:(?P<separator>[:.])(?P<minute>[0-5]\d))?\s*"
    r"(?:(?P<meridiem>[ap])\.?\s*m\.?)?(?!\d)",
    re.I,
)
_DATE_SHAPE_RE = re.compile(
    r"(?<!\d)(?:\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[./-]\d{1,2}[./-]\d{2,4})(?!\d)"
)
_ISO_RE = re.compile(r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)")
_MONTH_FIRST_RE = re.compile(
    rf"(?<!\w)(?P<month>{_MONTH_PATTERN})\.?\s+(?P<day>\d{{1,2}})"
    r"(?:st|nd|rd|th)?(?:\s*,\s*|\s+)(?P<year>\d{4})(?!\d)",
    re.I,
)
_DAY_FIRST_MONTH_RE = re.compile(
    rf"(?<!\d)(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\s+"
    rf"(?P<month>{_MONTH_PATTERN})\.?(?:\s*,\s*|\s+)(?P<year>\d{{4}})(?!\d)",
    re.I,
)
_BARE_PREFIX_RE = re.compile(r"(?:\b(?:at|around|by|for)\s*)$", re.I)
_NON_CLOCK_PREFIX_RE = re.compile(
    r"(?:\b(?:age|aged|token|phone(?:\s+number)?|mobile(?:\s+number)?|number|otp|pin|id)\b|"
    r"(?:వయసు|టోకెన్|ఫోన్|మొబైల్|నంబర్|उम्र|टोकन|फोन|मोबाइल|नंबर|"
    r"வயது|டோக்கன்|போன்|மொபைல்|எண்|ವಯಸ್ಸು|ಟೋಕನ್|ಫೋನ್|ಮೊಬೈಲ್|ಸಂಖ್ಯೆ|"
    r"വയസ്|ടോക്കൺ|ഫോൺ|മൊബൈൽ|നമ്പർ|वय|टोकन|फोन|मोबाईल|नंबर|"
    r"বয়স|টোকেন|ফোন|মোবাইল|নম্বর))\s*(?:is|[:#])?\s*$",
    re.I,
)
_NON_CLOCK_SUFFIX_RE = re.compile(
    r"^\s*(?:years?|yrs?|year\s+old|tokens?|people|patients?|"
    r"సంవత్సరాలు|టోకెన్లు|साल|वर्ष|टोकन|வயது|ஆண்டுகள்|டோக்கன்|"
    r"ವರ್ಷ|ಟೋಕನ್|വയസ്|വർഷം|ടോക്കൺ|वर्षे|टोकन|বছর|টোকেন)(?!\w)",
    re.I,
)
_ALTERNATIVE_RE = re.compile(
    r"(?:^|\s)(?:or|either|లేదా|या|அல்லது|ಅಥವಾ|അല്ലെങ്കിൽ|किंवा|অথবা)(?=\s|$|[,.?!])",
    re.I,
)
_RANGE_RE = re.compile(
    r"\bfrom\b.+\bto\b|\bbetween\b.+\band\b|"
    r"(?:నుంచి.+వరకు|से.+तक|முதல்.+வரை|ಇಂದ.+ವರೆಗೆ|മുതൽ.+വരെ|पासून.+पर्यंत|থেকে.+পর্যন্ত)",
    re.I,
)


def _normalize(text: str) -> str:
    value = unicodedata.normalize("NFKC", text or "")
    value = "".join(str(unicodedata.digit(char)) if char.isdecimal() else char for char in value)
    return re.sub(r"\s+", " ", value.casefold()).strip()


def _language_code(language: str) -> str:
    code = (language or "en").casefold().replace("_", "-").split("-", 1)[0]
    return code if code in _NUMBER_WORDS else "en"


def _phrase_regex(phrases: object) -> str:
    return "|".join(re.escape(value) for value in sorted(phrases, key=len, reverse=True))


def _overlaps(span: tuple[int, int], spans: list[tuple[int, int]]) -> bool:
    return any(span[0] < end and start < span[1] for start, end in spans)


def _near_non_clock(text: str, start: int, end: int) -> bool:
    before = text[max(0, start - 32) : start]
    after = text[end : min(len(text), end + 24)]
    return bool(_NON_CLOCK_PREFIX_RE.search(before) or _NON_CLOCK_SUFFIX_RE.search(after))


def _daypart(text: str, language: str) -> str | None:
    markers: set[str] = set()
    for code in {"en", language}:
        morning, later = _DAYPARTS[code]
        if re.search(rf"(?<!\w)(?:{_phrase_regex(morning)})(?!\w)", text):
            markers.add("am")
        if re.search(rf"(?<!\w)(?:{_phrase_regex(later)})(?!\w)", text):
            markers.add("pm")
    if len(markers) > 1:
        return "conflict"
    return next(iter(markers), None)


def _local_daypart(
    text: str,
    start: int,
    end: int,
    language: str,
) -> str | None:
    """Return only the daypart that belongs to this clock mention.

    A sentence can contain a spoken date and a later clock, for example
    ``ఆగస్టు ఇరవై ఎనిమిది సాయంత్రం ఐదు గంటలకు``.  Applying the one
    sentence-wide ``సాయంత్రం`` marker to every number turns the date's
    ``ఎనిమిది`` into a fabricated 8 PM clock.  Native dayparts normally lead
    their clock; English additionally permits the tightly-bound suffix
    ``five in the evening``.  Anything farther away remains ambiguous.
    """
    markers: set[str] = set()
    before = text[max(0, start - 32) : start]
    after = text[end : min(len(text), end + 24)]
    for code in {"en", language}:
        morning, later = _DAYPARTS[code]
        for phrases, marker in ((morning, "am"), (later, "pm")):
            pattern = _phrase_regex(phrases)
            if re.search(
                rf"(?<!\w)(?:{pattern})(?!\w)(?:\s+(?:at|around))?\s*$",
                before,
            ):
                markers.add(marker)
            if code == "en" and re.match(
                rf"\s+(?:in\s+the\s+)?(?:{pattern})(?!\w)",
                after,
            ):
                markers.add(marker)
    if len(markers) > 1:
        return "conflict"
    return next(iter(markers), None)


def _clock_candidates(hour: int, minute: int, meridiem: str | None) -> tuple[str, ...]:
    if meridiem:
        if not 1 <= hour <= 12:
            return ()
        hour = hour % 12 + (12 if meridiem == "pm" else 0)
        return (f"{hour:02d}:{minute:02d}",)
    if hour == 0 or hour >= 12:
        return (f"{hour:02d}:{minute:02d}",)
    return (f"{hour:02d}:{minute:02d}", f"{hour + 12:02d}:{minute:02d}")


def _add_occurrence(
    occurrences: list[tuple[int, int, tuple[str, ...]]],
    start: int,
    end: int,
    hour: int,
    minute: int,
    meridiem: str | None,
) -> None:
    if meridiem == "conflict":
        occurrences.append((start, end, ()))
        return
    candidates = _clock_candidates(hour, minute, meridiem)
    if candidates:
        occurrences.append((start, end, candidates))


def _word_meridiem(text: str, end: int, daypart: str | None) -> str | None:
    match = re.match(r"\s*(?P<marker>[ap])\.?\s*m\.?(?!\w)", text[end:], re.I)
    if match is None:
        return daypart
    marker = "am" if match.group("marker").casefold() == "a" else "pm"
    return "conflict" if daypart is not None and marker != daypart else marker


def _word_time_occurrences(
    text: str,
    language: str,
) -> list[tuple[int, int, tuple[str, ...]]]:
    occurrences: list[tuple[int, int, tuple[str, ...]]] = []
    consumed: list[tuple[int, int]] = []

    if language == "en":
        for phrase, hour in (("midnight", 0), ("noon", 12)):
            for match in re.finditer(rf"(?<!\w){phrase}(?!\w)", text):
                _add_occurrence(occurrences, *match.span(), hour, 0, None)
                consumed.append(match.span())
        spoken_24_hour = {
            word: value
            for word, value in _NUMBER_WORDS["en"].items()
            if 13 <= value <= 23
        }
        for match in re.finditer(
            rf"(?<!\w)(?P<hour>{_phrase_regex(spoken_24_hour)})\s+"
            r"hundred(?:\s+hours?)?(?!\w)",
            text,
        ):
            _add_occurrence(
                occurrences,
                *match.span(),
                spoken_24_hour[match.group("hour")],
                0,
                None,
            )
            consumed.append(match.span())

    for code in {language, "en"}:
        for phrase, (hour, minute) in sorted(_FRACTIONS.get(code, {}).items(), key=lambda item: -len(item[0])):
            for match in re.finditer(rf"(?<!\w){re.escape(phrase)}(?!\w)", text):
                if not _overlaps(match.span(), consumed) and not _near_non_clock(text, *match.span()):
                    marker = _word_meridiem(
                        text,
                        match.end(),
                        _local_daypart(text, *match.span(), code),
                    )
                    _add_occurrence(occurrences, *match.span(), hour, minute, marker)
                    consumed.append(match.span())

        numbers = _NUMBER_WORDS[code]
        hours = {word: number for word, number in numbers.items() if 1 <= number <= 12}
        minutes = {word: number for word, number in numbers.items() if number in {15, 30, 45}}
        hour_pattern = _phrase_regex(hours)
        minute_pattern = _phrase_regex(minutes)

        if code == "en":
            fractions = (
                (rf"(?<!\w)half\s+past\s+(?P<hour>{hour_pattern})(?!\w)", 30, False),
                (rf"(?<!\w)quarter\s+(?:past|after)\s+(?P<hour>{hour_pattern})(?!\w)", 15, False),
                (rf"(?<!\w)quarter\s+to\s+(?P<hour>{hour_pattern})(?!\w)", 45, True),
            )
            for pattern, minute, subtract in fractions:
                for match in re.finditer(pattern, text):
                    if _overlaps(match.span(), consumed) or _near_non_clock(text, *match.span()):
                        continue
                    hour = hours[match.group("hour")]
                    hour = (hour - 2) % 12 + 1 if subtract else hour
                    marker = _word_meridiem(
                        text,
                        match.end(),
                        _local_daypart(text, *match.span(), code),
                    )
                    _add_occurrence(occurrences, *match.span(), hour, minute, marker)
                    consumed.append(match.span())

        exact_pattern = re.compile(
            rf"(?<!\w)(?P<hour>{hour_pattern}){_MINUTE_CONNECTOR[code]}"
            rf"(?P<minute>{minute_pattern}){_MINUTE_UNIT[code]}(?!\w)"
        )
        for match in exact_pattern.finditer(text):
            if _overlaps(match.span(), consumed) or _near_non_clock(text, *match.span()):
                continue
            _add_occurrence(
                occurrences,
                *match.span(),
                hours[match.group("hour")],
                minutes[match.group("minute")],
                _word_meridiem(
                    text,
                    match.end(),
                    _local_daypart(text, *match.span(), code),
                ),
            )
            consumed.append(match.span())

        hour_only_pattern = re.compile(
            rf"(?<!\w)(?P<hour>{hour_pattern})"
            rf"(?P<suffix>\s*(?:{_CLOCK_SUFFIX[code]}))?(?!\w)"
        )
        for match in hour_only_pattern.finditer(text):
            if _overlaps(match.span(), consumed) or _near_non_clock(text, *match.span()):
                continue
            before = text[max(0, match.start() - 24) : match.start()]
            marker = _word_meridiem(
                text,
                match.end(),
                _local_daypart(text, *match.span(), code),
            )
            if not match.group("suffix") and marker is None and not _BARE_PREFIX_RE.search(before):
                continue
            _add_occurrence(occurrences, *match.span(), hours[match.group("hour")], 0, marker)
            consumed.append(match.span())

    return occurrences


def _clock_occurrences(
    normalized: str,
    language: str,
) -> list[tuple[int, int, tuple[str, ...]]]:
    code = _language_code(language)

    date_spans = [match.span() for match in _DATE_SHAPE_RE.finditer(normalized)]
    occurrences: list[tuple[int, int, tuple[str, ...]]] = []
    for match in _CLOCK_RE.finditer(normalized):
        if _overlaps(match.span(), date_spans) or _near_non_clock(normalized, *match.span()):
            continue
        before = normalized[max(0, match.start() - 24) : match.start()]
        after = normalized[match.end() : match.end() + 24]
        separator = match.group("separator")
        explicit_meridiem = match.group("meridiem")
        daypart = _local_daypart(normalized, *match.span(), code)
        if explicit_meridiem:
            marker = "am" if explicit_meridiem.casefold() == "a" else "pm"
            if daypart is not None and marker != daypart:
                return []
        else:
            marker = daypart
        clock_suffix = any(re.match(rf"\s*(?:{suffix})", after) for suffix in _CLOCK_SUFFIX.values())
        if match.group("minute") is None:
            if re.match(r"[:.]\d", after):
                continue
            if marker is None and not clock_suffix and not _BARE_PREFIX_RE.search(before):
                continue
        elif separator == "." and marker is None and not clock_suffix and not _BARE_PREFIX_RE.search(before):
            continue
        _add_occurrence(
            occurrences,
            *match.span(),
            int(match.group("hour")),
            int(match.group("minute") or 0),
            marker,
        )

    occurrences.extend(_word_time_occurrences(normalized, code))
    return sorted(set(occurrences), key=lambda item: (item[0], item[1], item[2]))


def clock_time_mentions(
    text: str,
    language: str = "en",
) -> tuple[tuple[str, ...], ...]:
    """Return every safely attributable clock mention in order.

    Each item contains the possible canonical 24-hour values for one mention.
    Unlike :func:`explicit_clock_times`, this is intentionally able to inspect
    several times in one sentence so a grounded-response firewall can reject a
    reply that mixes one real slot with an invented one.
    """
    normalized = _normalize(text)
    if not normalized:
        return ()
    return tuple(item[2] for item in _clock_occurrences(normalized, language))


def explicit_clock_times(text: str, language: str = "en") -> tuple[str, ...]:
    """Return the caller's one clock choice, preserving AM/PM ambiguity.

    An empty tuple means there was no safely attributable single clock choice.
    """
    normalized = _normalize(text)
    if not normalized or _ALTERNATIVE_RE.search(normalized) or _RANGE_RE.search(normalized):
        return ()
    occurrences = _clock_occurrences(normalized, language)
    distinct = {item[2] for item in occurrences}
    return next(iter(distinct)) if len(distinct) == 1 else ()


def _phrase_matches(text: str, values: dict[str, int]) -> list[tuple[int, int, int]]:
    matches: list[tuple[int, int, int]] = []
    used: list[tuple[int, int]] = []
    for phrase in sorted(values, key=len, reverse=True):
        for match in re.finditer(rf"(?<!\w){re.escape(phrase)}(?!\w)", text):
            if not _overlaps(match.span(), used):
                matches.append((*match.span(), values[phrase]))
                used.append(match.span())
    return matches


def explicit_booking_date(text: str, today: date, language: str = "en") -> str | None:
    """Return one explicit caller date as ISO, or ``None`` if it is unsafe."""
    normalized = _normalize(text)
    if not normalized or _ALTERNATIVE_RE.search(normalized) or _RANGE_RE.search(normalized):
        return None
    candidates: list[date] = []

    for match in _ISO_RE.finditer(normalized):
        try:
            candidates.append(date(*(int(part) for part in match.groups())))
        except ValueError:
            return None

    for pattern in (_MONTH_FIRST_RE, _DAY_FIRST_MONTH_RE):
        for match in pattern.finditer(normalized):
            try:
                candidates.append(
                    date(
                        int(match.group("year")),
                        _MONTHS[match.group("month").casefold()],
                        int(match.group("day")),
                    )
                )
            except ValueError:
                return None

    for shape in re.finditer(r"(?<!\d)(\d{1,2})([./-])(\d{1,2})\2(\d{2,4})(?!\d)", normalized):
        if _overlaps(shape.span(), [match.span() for match in _ISO_RE.finditer(normalized)]):
            continue
        if len(shape.group(4)) != 4:
            return None
        day, month, year = int(shape.group(1)), int(shape.group(3)), int(shape.group(4))
        if day <= 12:
            return None
        try:
            candidates.append(date(year, month, day))
        except ValueError:
            return None

    code = _language_code(language)
    relatives = dict(_RELATIVE_DATES["en"])
    relatives.update(_RELATIVE_DATES[code])
    for _, _, offset in _phrase_matches(normalized, relatives):
        candidates.append(today + timedelta(days=offset))

    weekdays = {word: index for index, word in enumerate(_WEEKDAYS["en"])}
    weekdays.update({word: index for index, word in enumerate(_WEEKDAYS[code])})
    weekdays.update(_LONG_WEEKDAYS.get(code, {}))
    for start, _, weekday in _phrase_matches(normalized, weekdays):
        delta = (weekday - today.weekday()) % 7
        before = normalized[max(0, start - 8) : start]
        if re.search(r"\bnext\s*$", before) and delta == 0:
            delta = 7
        candidates.append(today + timedelta(days=delta))

    distinct = {candidate.isoformat() for candidate in candidates}
    return next(iter(distinct)) if len(distinct) == 1 else None

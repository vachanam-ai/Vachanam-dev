"""Fast, branch-local FAQ candidate retrieval.

The LLM still turns the selected database answer into natural speech.  This
module only decides whether a common clinic question is already covered, so a
model can never create a duplicate "ask the doctor" task for a known fact.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import time

from agent.services.telugu_dates import telugu_time_range


@dataclass(frozen=True)
class FaqMatch:
    question: str
    answer: str
    intent: str


_INTENT_TERMS = {
    "consultation_fee": (
        "consultation fee", "consultation fees", "doctor fee", "doctor fees",
        "fee", "fees", "charge", "cost", "ఫీజు", "ఫీస్", "పీస్",
        "कंसल्टेशन फीस", "फीस", "फ़ीस", "கட்டணம்", "ஃபீஸ்", "ಫೀಸ್",
        "ಶುಲ್ಕ", "फी", "ফি",
    ),
    "clinic_hours": (
        "clinic timing", "clinic timings", "opening time", "closing time",
        "are you open", "open on", "క్లినిక్ టైమింగ్", "టైమింగ్స్", "తెరిచి",
        "क्लिनिक टाइम", "खुल", "நேரம்", "திறந்திரு", "ಸಮಯ", "ತೆರೆದ",
    ),
    "location": (
        "where exactly", "clinic located", "clinic location", "address", "landmark",
        "ఎక్కడ", "అడ్రస్", "లొకేషన్", "कहाँ", "पता", "எங்கே", "முகவரி",
        "ಎಲ್ಲಿ", "ವಿಳಾಸ", "कुठे", "ঠিকানা",
    ),
    "parking": (
        "parking", "park", "bike", "motorbike", "scooter", "two wheeler",
        "vehicle", "బైక్", "బండి", "వాహనం", "పార్కింగ్", "పార్క్",
        "पार्किंग", "पार्क", "बाइक", "गाड़ी", "वाहन",
        "பார்க்கிங்", "பைக்", "வண்டி", "பார்க்",
        "ಪಾರ್ಕಿಂಗ್", "ಬೈಕ್", "ಗಾಡಿ", "ಪಾರ್ಕ್",
    ),
    "payment": (
        "payment method", "cash", "upi", "card", "పేమెంట్", "నగదు", "కార్డ్",
        "भुगतान", "कैश", "பணம்", "கார்டு", "ಪಾವತಿ", "ನಗದು",
    ),
    "insurance": ("insurance", "ఇన్సూరెన్స్", "बीमा", "इंश्योरेंस", "காப்பீடு", "ವಿಮೆ"),
    "home_visit": (
        "home visit", "home visits", "ఇంటికి వస్త", "होम विजिट", "घर आते",
        "வீட்டுக்கு", "ಮನೆಗೆ", "घर भेट",
    ),
    "services": (
        "treatments", "services", "what do you treat", "చికిత్స", "సర్వీసెస్",
        "ట్రీట్మెంట్", "इलाज", "सेवाएं", "சிகிச்சை", "சேவை", "ಚಿಕಿತ್ಸೆ",
    ),
    "followup_policy": (
        "follow-up visit", "follow up visit", "followup visit", "follow-up free",
        "follow up free", "ఫాలో అప్", "फॉलो अप", "ஃபாலோ அப்", "ಫಾಲೋ ಅಪ್",
    ),
}

_STOP = {
    "a", "an", "the", "is", "are", "do", "does", "what", "which", "for",
    "of", "your", "you", "clinic", "doctor", "dr", "please", "about", "with",
}


def decode_faq(value) -> list[dict]:
    """Accept decoded JSONB and the legacy double-encoded JSONB representation."""
    for _ in range(2):
        if not isinstance(value, str):
            break
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return []
    if not isinstance(value, (list, tuple)):
        return []
    return [row for row in value if isinstance(row, dict)]


def _norm(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "").casefold()
    return " ".join(re.findall(r"[^\W_]+", text, flags=re.UNICODE))


def _intent(value: str) -> str | None:
    text = _norm(value)
    for name, terms in _INTENT_TERMS.items():
        if any(_norm(term) in text for term in terms):
            return name
    return None


def _content_words(value: str) -> set[str]:
    return {word for word in _norm(value).split() if len(word) > 2 and word not in _STOP}


def find_faq_match(utterance: str, faq_rows) -> FaqMatch | None:
    """Return only high-confidence matches; uncertainty stays with the main LLM."""
    rows = []
    for row in decode_faq(faq_rows):
        q = str(row.get("q") or "").strip()
        a = str(row.get("a") or "").strip()
        if q and a:
            rows.append((q, a, _intent(q)))
    if not rows:
        return None

    asked_intent = _intent(utterance)
    if asked_intent:
        candidates = [(q, a) for q, a, intent in rows if intent == asked_intent]
        if len(candidates) == 1:
            q, a = candidates[0]
            return FaqMatch(q, a, asked_intent)
        if candidates:
            words = _content_words(utterance)
            ranked = sorted(
                ((len(words & _content_words(q)), q, a) for q, a in candidates),
                reverse=True,
            )
            if ranked[0][0] > 0:
                _, q, a = ranked[0]
                return FaqMatch(q, a, asked_intent)

    # Same-language/custom FAQ fallback. Requiring two shared content words
    # avoids turning a vague fragment into an authoritative clinic fact.
    words = _content_words(utterance)
    ranked = sorted(
        ((len(words & _content_words(q)), q, a, intent) for q, a, intent in rows),
        reverse=True,
    )
    if ranked and ranked[0][0] >= 2:
        _, q, a, intent = ranked[0]
        return FaqMatch(q, a, intent or "custom")
    return None


def natural_fallback(match: FaqMatch, lang_code: str) -> str:
    """Self-contained fallback when the small natural-language pass times out."""
    answer = match.answer.strip().rstrip(".")
    if match.intent == "consultation_fee" and re.fullmatch(r"[\d,]+(?:\.\d+)?", answer):
        currency = {
            "te": "రూపాయలు", "hi": "रुपये", "ta": "ரூபாய்",
            "kn": "ರೂಪಾಯಿ", "mr": "रुपये", "en": "rupees",
        }.get(lang_code, "rupees")
        answer = f"{answer} {currency}"
        direct = {
            "te": f"కన్సల్టేషన్ ఫీజు {answer} అండి.",
            "hi": f"कंसल्टेशन फीस {answer} है जी।",
            "ta": f"கன்சல்டேஷன் பீஸ் {answer}ங்க.",
            "kn": f"ಕನ್ಸಲ್ಟೇಶನ್ ಫೀಸ್ {answer} ರೀ.",
            "mr": f"कन्सल्टेशन फी {answer} आहे.",
            "en": f"The consultation fee is {answer}.",
        }
        return direct.get(lang_code, direct["en"])
    if match.intent == "clinic_hours":
        localized = _clinic_hours(answer, lang_code)
        if localized:
            return localized
    if match.intent == "parking" and re.match(
        r"^(?:yes|available|avunu|ఉంది|అవును|हाँ|हां|जी|ஆம்|ஆமாம்|ಹೌದು|हो)\b",
        answer,
        flags=re.I,
    ):
        direct = {
            "te": "అవునండి, మా క్లినిక్‌లో పార్కింగ్ అందుబాటులో ఉంది.",
            "hi": "जी हाँ, क्लिनिक में पार्किंग उपलब्ध है।",
            "ta": "ஆமாங்க, கிளினிக்கில் பார்க்கிங் வசதி இருக்கு.",
            "kn": "ಹೌದು, ಕ್ಲಿನಿಕ್‌ನಲ್ಲಿ ಪಾರ್ಕಿಂಗ್ ಸೌಲಭ್ಯ ಇದೆ.",
            "mr": "हो, क्लिनिकमध्ये पार्किंग उपलब्ध आहे.",
            "en": "Yes, parking is available at the clinic.",
        }
        return direct.get(lang_code, direct["en"])
    if lang_code == "te":
        subject = {
            "consultation_fee": "కన్సల్టేషన్ ఫీజు", "clinic_hours": "మా క్లినిక్ టైమింగ్స్",
            "location": "మా క్లినిక్ లొకేషన్", "parking": "పార్కింగ్ గురించి",
            "payment": "పేమెంట్ గురించి", "insurance": "ఇన్సూరెన్స్ గురించి",
            "home_visit": "హోమ్ విజిట్ గురించి", "services": "మా క్లినిక్‌లో చికిత్సలు",
            "followup_policy": "ఫాలో అప్ విజిట్ గురించి",
        }.get(match.intent, "క్లినిక్ సమాచారం")
        return f"{subject} {answer} అండి."
    if lang_code == "hi":
        return f"क्लिनिक की जानकारी के अनुसार, {answer} जी।"
    if lang_code == "ta":
        return f"கிளினிக் தகவலின்படி, {answer}ங்க."
    if lang_code == "kn":
        return f"ಕ್ಲಿನಿಕ್ ಮಾಹಿತಿಯ ಪ್ರಕಾರ, {answer} ರೀ."
    if lang_code == "mr":
        return f"क्लिनिकच्या माहितीनुसार, {answer}."
    return f"According to the clinic, {answer}."


_CLOCK_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12,
}
_CLOCK_TOKEN = r"(?:\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
_HOURS_RANGE = re.compile(
    rf"(?P<start>{_CLOCK_TOKEN})(?::(?P<start_min>\d{{2}}))?\s*"
    r"(?P<start_mer>a\.?\s*m\.?|p\.?\s*m\.?)?\s*"
    r"(?:to|until|till|[-–—])\s*"
    rf"(?P<end>{_CLOCK_TOKEN})(?::(?P<end_min>\d{{2}}))?\s*"
    r"(?P<end_mer>a\.?\s*m\.?|p\.?\s*m\.?)?",
    re.I,
)


def _clock_hour(raw: str) -> int:
    return int(raw) if raw.isdigit() else _CLOCK_WORDS[raw.casefold()]


def _clock_value(hour_raw: str, minute_raw: str | None, meridiem: str | None) -> time:
    hour = _clock_hour(hour_raw)
    minute = int(minute_raw or 0)
    mer = re.sub(r"[^amp]", "", (meridiem or "").casefold())
    if mer == "pm" and hour < 12:
        hour += 12
    elif mer == "am" and hour == 12:
        hour = 0
    return time(hour, minute)


_CLOCK_NUMBERS = {
    "hi": {
        1: "एक", 2: "दो", 3: "तीन", 4: "चार", 5: "पाँच", 6: "छह", 7: "सात",
        8: "आठ", 9: "नौ", 10: "दस", 11: "ग्यारह", 12: "बारह", 15: "पंद्रह", 30: "तीस", 45: "पैंतालीस",
    },
    "ta": {
        1: "ஒன்று", 2: "இரண்டு", 3: "மூன்று", 4: "நான்கு", 5: "ஐந்து", 6: "ஆறு", 7: "ஏழு",
        8: "எட்டு", 9: "ஒன்பது", 10: "பத்து", 11: "பதினொன்று", 12: "பன்னிரண்டு", 15: "பதினைந்து", 30: "முப்பது", 45: "நாற்பத்தைந்து",
    },
    "kn": {
        1: "ಒಂದು", 2: "ಎರಡು", 3: "ಮೂರು", 4: "ನಾಲ್ಕು", 5: "ಐದು", 6: "ಆರು", 7: "ಏಳು",
        8: "ಎಂಟು", 9: "ಒಂಬತ್ತು", 10: "ಹತ್ತು", 11: "ಹನ್ನೊಂದು", 12: "ಹನ್ನೆರಡು", 15: "ಹದಿನೈದು", 30: "ಮೂವತ್ತು", 45: "ನಲವತ್ತೈದು",
    },
    "mr": {
        1: "एक", 2: "दोन", 3: "तीन", 4: "चार", 5: "पाच", 6: "सहा", 7: "सात",
        8: "आठ", 9: "नऊ", 10: "दहा", 11: "अकरा", 12: "बारा", 15: "पंधरा", 30: "तीस", 45: "पंचेचाळीस",
    },
}


def _clock_phrase(value: time, lang_code: str) -> str:
    """Natural clock speech for the four non-Telugu production languages."""
    hour = value.hour % 12 or 12
    numbers = _CLOCK_NUMBERS[lang_code]
    hour_word = numbers[hour]
    minute = "" if value.minute == 0 else f" {numbers.get(value.minute, value.minute)}"
    if lang_code == "hi":
        daypart = "सुबह" if value.hour < 12 else ("दोपहर" if value.hour < 16 else "शाम")
        return f"{daypart} {hour_word} बजे" if not minute else f"{daypart} {hour_word} बजकर{minute} मिनट"
    if lang_code == "ta":
        daypart = "காலை" if value.hour < 12 else ("மதியம்" if value.hour < 16 else "மாலை")
        return f"{daypart} {hour_word} மணி" + (f"{minute} நிமிடம்" if minute else "")
    if lang_code == "kn":
        daypart = "ಬೆಳಗ್ಗೆ" if value.hour < 12 else ("ಮಧ್ಯಾಹ್ನ" if value.hour < 16 else "ಸಂಜೆ")
        return f"{daypart} {hour_word} ಗಂಟೆ" + (f"{minute} ನಿಮಿಷ" if minute else "")
    daypart = "सकाळी" if value.hour < 12 else ("दुपारी" if value.hour < 16 else "संध्याकाळी")
    return f"{daypart} {hour_word} वाजता" if not minute else f"{daypart} {hour_word} वाजून{minute} मिनिटांनी"


def _clinic_hours(answer: str, lang_code: str) -> str | None:
    """Localize the common English DB-hours shape without an LLM round trip."""
    found = _HOURS_RANGE.search(answer or "")
    if found is None:
        return None
    start_mer = found.group("start_mer")
    end_mer = found.group("end_mer")
    start = _clock_value(
        found.group("start"), found.group("start_min"), start_mer
    )
    # Clinic rows often say "9 AM to 5".  A smaller closing hour after an AM
    # opening is unambiguously afternoon; treating it as 5 AM is the old bug.
    inferred_end_mer = end_mer
    if not inferred_end_mer and start_mer:
        end_hour = _clock_hour(found.group("end"))
        inferred_end_mer = "pm" if start.hour < 12 and end_hour < start.hour else start_mer
    end = _clock_value(
        found.group("end"), found.group("end_min"), inferred_end_mer
    )
    closed_sunday = bool(re.search(
        r"sundays?\s+(?:is\s+)?(?:closed?|close)|closed?\s+on\s+sundays?",
        answer, re.I,
    ))
    if lang_code == "te":
        speech = f"మా క్లినిక్ {telugu_time_range(start, end)} తెరిచి ఉంటుందండి."
        return speech + (" Sunday రోజు సెలవు అండి." if closed_sunday else "")
    if lang_code == "en":
        def _en_clock(value: time) -> str:
            hour = value.hour % 12 or 12
            minute = f":{value.minute:02d}" if value.minute else ""
            return f"{hour}{minute} {'AM' if value.hour < 12 else 'PM'}"
        speech = f"Our clinic is open from {_en_clock(start)} to {_en_clock(end)}."
        return speech + (" It is closed on Sundays." if closed_sunday else "")
    if lang_code not in _CLOCK_NUMBERS:
        return None
    start_speech, end_speech = _clock_phrase(start, lang_code), _clock_phrase(end, lang_code)
    templates = {
        "hi": f"हमारा क्लिनिक {start_speech} से {end_speech} तक खुला रहता है जी।",
        "ta": f"எங்கள் கிளினிக் {start_speech} முதல் {end_speech} வரை திறந்திருக்கும்ங்க.",
        "kn": f"ನಮ್ಮ ಕ್ಲಿನಿಕ್ {start_speech}ಯಿಂದ {end_speech}ಯವರೆಗೆ ತೆರೆದಿರುತ್ತದೆ ರೀ.",
        "mr": "",
    }
    if lang_code == "mr":
        start_boundary = start_speech.replace("वाजता", "वाजल्यापासून").replace("मिनिटांनी", "मिनिटांपासून")
        end_boundary = end_speech.replace("वाजता", "वाजेपर्यंत").replace("मिनिटांनी", "मिनिटांपर्यंत")
        templates["mr"] = f"आमचं क्लिनिक {start_boundary} {end_boundary} उघडं असतं."
    sunday = {
        "hi": " Sunday को बंद रहता है।", "ta": " Sunday விடுமுறைங்க.",
        "kn": " Sunday ರಜೆ.", "mr": " Sunday सुट्टी असते.",
    }
    speech = templates[lang_code]
    if closed_sunday:
        speech += sunday[lang_code]
    return speech


def _telugu_clinic_hours(answer: str) -> str | None:
    """Backward-compatible name used by older tests/callers."""
    return _clinic_hours(answer, "te")

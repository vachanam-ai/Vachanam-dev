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
    "parking": ("parking", "పార్కింగ్", "पार्किंग", "பார்க்கிங்", "ಪಾರ್ಕಿಂಗ್"),
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
        answer = f"{answer} rupees" if lang_code == "en" else f"{answer} రూపాయలు"
    if lang_code == "te":
        if match.intent == "clinic_hours":
            localized = _telugu_clinic_hours(answer)
            if localized:
                return localized
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


def _telugu_clinic_hours(answer: str) -> str | None:
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
    speech = f"మా క్లినిక్ {telugu_time_range(start, end)} తెరిచి ఉంటుందండి."
    if re.search(r"sundays?\s+(?:is\s+)?(?:closed?|close)|closed?\s+on\s+sundays?", answer, re.I):
        speech += " Sunday రోజు సెలవు అండి."
    return speech

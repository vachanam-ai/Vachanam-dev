"""Small deterministic parsers for facts that must never be improvised."""
from __future__ import annotations

import re
from datetime import time
from typing import Any, Iterable


_SPECIALTIES: dict[str, tuple[str, ...]] = {
    "skin": ("dermatologist", "dermatology", "skin specialist", "skin", "స్కిన్", "చర్మ"),
    "orthopedic": (
        "orthopaedic", "orthopedic", "orthopedics", "orthopaedics",
        "ortho", "ఆర్థో", "ఆర్తో", "ఎముక",
    ),
    "dental": ("dentist", "dental", "tooth", "teeth", "దంత", "పంటి", "పళ్ళ", "పళ్ల"),
    "children": (
        "paediatric", "pediatric", "children specialist", "child specialist",
        "children", "child", "kids", "పిల్లల", "పిల్ల",
    ),
    "cardiology": ("cardiologist", "cardiology", "cardiac", "heart", "గుండె"),
    "ent": ("ear nose throat", "e.n.t", "ent", "చెవి", "ముక్కు", "గొంతు"),
    "gynecology": (
        "gynaecologist", "gynecologist", "gynaecology", "gynecology",
        "obstetrician", "గైనకాలజ", "గైనిక్", "స్త్రీ",
    ),
    "general": ("general physician", "general medicine", "physician", "general doctor"),
    "neurology": ("neurologist", "neurology", "న్యూరో"),
    "psychiatry": ("psychiatrist", "psychiatry", "mental health", "సైకియాట్ర"),
    "ophthalmology": ("ophthalmologist", "ophthalmology", "eye doctor", "కంటి"),
    "urology": ("urologist", "urology", "యూరాలజ"),
    "gastro": ("gastroenterologist", "gastroenterology", "gastro", "గ్యాస్ట్రో"),
    "pulmonology": ("pulmonologist", "pulmonology", "chest specialist", "పల్మనాలజ"),
}

_DOCTOR_TERMS = ("doctor", "doctors", "డాక్టర్", "వైద్యుడు", "డాక్టర్లు")
_LIST_TERMS = (
    "what doctors", "which doctors", "doctor list", "doctors available",
    "who are the doctors", "any doctors", "ఏ డాక్టర్లు", "ఎవరెవరు",
    "ఎవరు ఉన్నారు", "డాక్టర్ల లిస్ట్", "డాక్టర్స్ లిస్ట్",
)


def _has_alias(text: str, alias: str) -> bool:
    if alias.isascii():
        return re.search(rf"(?<![a-z]){re.escape(alias)}(?![a-z])", text) is not None
    return alias in text


def _specialty(text: str) -> str | None:
    low = (text or "").lower()
    for key, aliases in _SPECIALTIES.items():
        if any(_has_alias(low, alias) for alias in aliases):
            return key
    return None


def _doctor_specialty(doctor: Any) -> str | None:
    terms = " ".join(
        [
            str(getattr(doctor, "specialization", "") or ""),
            *[str(x) for x in (getattr(doctor, "routing_keywords", None) or [])],
        ]
    )
    return _specialty(terms)


def doctor_roster_reply(
    text: str, lang_code: str, doctors: Iterable[Any]
) -> str | None:
    """Answer explicit roster/specialty questions from the cached DB roster."""
    lang = (lang_code or "").lower()
    if lang not in {"te", "en", "hi"}:
        return None
    low = (text or "").lower().strip()
    if not low or not any(term in low for term in _DOCTOR_TERMS):
        return None
    roster = list(doctors)
    if not roster:
        return None

    named = [
        d for d in roster
        if len(str(getattr(d, "name", "") or "").strip()) >= 3
        and str(getattr(d, "name", "")).lower().strip() in low
    ]
    requested = _specialty(low)
    matched = named or (
        [d for d in roster if _doctor_specialty(d) == requested]
        if requested else []
    )
    is_list = any(term in low for term in _LIST_TERMS)
    if not requested and not named and not is_list:
        return None

    def detail(d: Any) -> str:
        name = str(getattr(d, "name", "") or "").strip()
        spec = str(getattr(d, "specialization", "") or "").strip()
        return f"{name} — {spec}" if spec else name

    if matched:
        joined = ", ".join(detail(d) for d in matched)
        if lang == "te":
            return f"[happily] అవునండి, {joined} ఉన్నారు. అపాయింట్‌మెంట్ కావాలా?"
        if lang == "hi":
            return f"[happily] जी हाँ, {joined} उपलब्ध हैं। अपॉइंटमेंट चाहिए?"
        return f"[happily] Yes, we have {joined}. Would you like an appointment?"

    details = ", ".join(detail(d) for d in roster)
    if requested:
        if lang == "te":
            return (
                "[softly] లేరండి, ఆ స్పెషాలిటీ డాక్టర్ మా దగ్గర లేరు. "
                f"మా దగ్గర {details} ఉన్నారు."
            )
        if lang == "hi":
            return (
                "[softly] नहीं, उस स्पेशलिटी के डॉक्टर हमारे यहाँ नहीं हैं। "
                f"हमारे यहाँ {details} उपलब्ध हैं।"
            )
        return (
            "[softly] No, we do not have that specialist. "
            f"We currently have {details}."
        )

    if lang == "te":
        return f"[happily] మా దగ్గర {details} ఉన్నారు. ఏ డాక్టర్‌కి అపాయింట్‌మెంట్ కావాలి?"
    if lang == "hi":
        return f"[happily] हमारे यहाँ {details} उपलब्ध हैं। किस डॉक्टर का अपॉइंटमेंट चाहिए?"
    return f"[happily] We currently have {details}. Which doctor would you like?"


_TELUGU_HOURS = {
    "పన్నెండు": 12, "పదకొండు": 11, "పది": 10, "తొమ్మిది": 9,
    "ఎనిమిది": 8, "ఏడు": 7, "ఆరు": 6, "ఐదు": 5, "నాలుగు": 4,
    "మూడు": 3, "రెండు": 2, "ఒకటి": 1,
}
_ENGLISH_HOURS = {
    "twelve": 12, "eleven": 11, "ten": 10, "nine": 9, "eight": 8,
    "seven": 7, "six": 6, "five": 5, "four": 4, "three": 3,
    "two": 2, "one": 1,
}
_TIME_MARKERS = (
    "am", "pm", "a.m", "p.m", "o'clock", "clock", "hour", "at ",
    "morning", "afternoon", "evening", "night", "గంట", "కి", "కు",
    "ఉదయం", "మధ్యాహ్నం", "సాయంత్రం", "రాత్రి", "టైమ్",
)
_CORRECTION_MARKERS = ("no", "not", "actually", "i said", "కాదు", "లేదు", "అన్నాను", "అంటే")


def extract_exact_time(text: str, reference: time | None = None) -> time | None:
    """Extract a short exact-time correction, inheriting the prior day-part."""
    low = re.sub(r"\s+", " ", (text or "").lower()).strip()
    if not low:
        return None
    explicit_marker = any(marker in low for marker in _TIME_MARKERS)
    correction = any(marker in low for marker in _CORRECTION_MARKERS)

    hour: int | None = None
    minute = 0
    match = re.search(
        r"(?<!\d)([01]?\d|2[0-3])(?:[:.]([0-5]\d))?\s*(a\.?m\.?|p\.?m\.?)?(?!\d)",
        low,
    )
    period = ""
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2) or 0)
        period = (match.group(3) or "").replace(".", "")
        if not explicit_marker and not correction:
            bare = re.fullmatch(r"\s*\d{1,2}(?:[:.]\d{2})?\s*", low)
            if bare is None:
                return None
    else:
        for word, value in {**_TELUGU_HOURS, **_ENGLISH_HOURS}.items():
            if word in low:
                hour = value
                if "న్నర" in low or "half" in low or "thirty" in low:
                    minute = 30
                break
        if hour is None:
            return None
        if not explicit_marker and not correction:
            compact = re.sub(r"[\s,?.!]", "", low)
            if compact not in {
                *[re.sub(r"\s", "", x) for x in _TELUGU_HOURS],
                *[re.sub(r"\s", "", x) for x in _ENGLISH_HOURS],
            }:
                return None

    if period.startswith("p") or any(x in low for x in ("afternoon", "evening", "night", "మధ్యాహ్నం", "సాయంత్రం", "రాత్రి")):
        if hour < 12:
            hour += 12
    elif period.startswith("a") or any(x in low for x in ("morning", "ఉదయం")):
        if hour == 12:
            hour = 0
    elif hour <= 12 and reference is not None and reference.hour >= 12:
        if hour < 12:
            hour += 12

    try:
        return time(hour, minute)
    except ValueError:
        return None


# --------------------------------------------------------------------------
# Task 2.3 (voice_grounding_gate tts_node tripwire, 2026-07-30): a NARROW,
# conservative detector for "this text states a specific clock time" — used
# ONLY to decide whether an ungrounded reply needs to be blocked. A bare
# number (a token, an age, a phone digit) never trips it; only an explicit
# digit clock (11:30, 9.45) or a digit/number-word paired with an explicit
# am/pm/o'clock/day-part marker does. Err toward NOT matching — a missed
# hallucination is a smaller harm than blocking a legitimate reply into dead
# air (spec 2026-07-30-voice-prompt-redesign-design.md §4.1/§7).
# --------------------------------------------------------------------------
_CLOCK_DIGIT_RE = re.compile(
    r"(?<!\d)([01]?\d|2[0-3])[:.]([0-5]\d)(?!\d)"          # 11:30 / 9.45
    r"|(?<!\d)([01]?\d|2[0-3])\s*(a\.?m\.?|p\.?m\.?)(?!\w)",  # 5 pm / 11am
    re.IGNORECASE,
)
_HOUR_WORDS = tuple({**_TELUGU_HOURS, **_ENGLISH_HOURS})


def asserts_clock_time(text: str) -> bool:
    """True only when TEXT states a specific clock time. Conservative by
    design — a false negative (a hallucinated time slips through) is safer
    than a false positive (a legitimate reply replaced by dead air)."""
    low = (text or "").lower()
    if not low:
        return False
    if _CLOCK_DIGIT_RE.search(low):
        return True
    if any(marker in low for marker in _TIME_MARKERS) and any(
        word in low for word in _HOUR_WORDS
    ):
        return True
    return False


# --------------------------------------------------------------------------
# Task 2.2 (voice_grounding_gate, 2026-07-30): fee/hours/booking-status intent
# classification + FAQ matching. Deliberately narrow — te/en/hi only, mirroring
# doctor_roster_reply's language scope; an unrecognized/unsupported turn
# returns None and the caller falls through to the unchanged LLM path.
# --------------------------------------------------------------------------
_BOOKING_STATUS_TERMS = (
    "my token", "token number", "which token", "queue", "how many ahead",
    "how many people", "my turn", "when is my turn",
    "నా టోకెన్", "ఎన్నో నంబర్", "క్యూ", "నా టర్న్", "ఎంతమంది ఉన్నారు",
    "मेरा टोकन", "कौन सा टोकन", "कतार", "मेरी बारी",
)
_FEE_TERMS = (
    "fee", "fees", "charge", "charges", "cost", "price", "how much",
    "ఫీజు", "ఫీజు ఎంత", "డబ్బు ఎంత", "రేటు", "శుల్కం", "ఎంత తీసుకుంటారు",
    "फीस", "शुल्क", "कितना पैसा", "कितने पैसे", "रेट",
)
_HOURS_TERMS = (
    "hours", "timing", "timings", "opening time", "closing time",
    "when do you open", "when do you close", "what time do you open",
    "what time do you close", "clinic hours",
    "టైమింగ్స్", "టైమింగ", "ఎప్పుడు తెరుస్తారు", "ఎప్పుడు మూస్తారు", "పని వేళలు",
    "समय", "टाइमिंग", "कब खुलते", "कब बंद होते", "क्लिनिक का समय",
)


def clinic_fact_intent(text: str) -> str | None:
    """Classify a turn as a booking-status/fee/hours clinic-fact question, or
    None. Order matters: booking-status phrasing ("my token") is checked
    first so it can never be shadowed by a generic fee/hours word."""
    low = (text or "").lower().strip()
    if not low:
        return None
    if any(term in low for term in _BOOKING_STATUS_TERMS):
        return "booking_status"
    if any(term in low for term in _FEE_TERMS):
        return "fee"
    if any(term in low for term in _HOURS_TERMS):
        return "hours"
    return None


def match_faq_by_intent(intent: str, faq: Iterable[dict] | None) -> str | None:
    """Return the FIRST FAQ answer whose OWN question shares the same
    fee/hours vocabulary as the caller's intent — never a different row, and
    never anything not already verbatim in the clinic's own FAQ data."""
    terms = {"fee": _FEE_TERMS, "hours": _HOURS_TERMS}.get(intent)
    if not terms:
        return None
    for item in faq or []:
        q = str((item or {}).get("q") or "").lower()
        a = str((item or {}).get("a") or "").strip()
        if a and any(term in q for term in terms):
            return a
    return None


_CLOSE_REPLIES = {
    "no", "no thanks", "nothing", "nothing else", "that's all", "that is all",
    "thank you", "thanks", "okay thanks", "ok thanks", "bye",
    "లేదు", "వద్దు", "అంతే", "థాంక్యూ", "ధన్యవాదాలు", "బై",
    "नहीं", "नहीं धन्यवाद", "बस", "धन्यवाद", "ठीक है धन्यवाद", "बाय",
}


def is_short_close_reply(text: str) -> bool:
    """True only for an unambiguous short answer to “anything else?”"""
    normalized = re.sub(r"[^\w\s'\u0900-\u097f\u0c00-\u0c7f]", "", (text or "").lower())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized in _CLOSE_REPLIES

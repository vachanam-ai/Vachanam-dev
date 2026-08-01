"""Public entry points and runtime date-table builder for Vachanam."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import zoneinfo

from agent.prompts.grounded_prompt import build_grounded_prompt


@dataclass
class DoctorContext:
    id: str
    name: str
    specialization: str
    routing_keywords: list[str]
    booking_type: str  # token | appointment
    is_default: bool
    working_hours_start: str = ""  # HH:MM (24h) or empty when unset
    working_hours_end: str = ""
    available_weekdays: list[int] | None = None  # 0=Mon..6=Sun; None/[] = all


# Generalized, privacy-safe disclosures per active language
DISCLOSURES: dict[str, str] = {
    "te": "ఇది క్లినిక్ AI అసిస్టెంట్ అండి. మీ అపాయింట్‌మెంట్ ప్రాసెస్ చేయడం కోసం ఈ కాల్ రికార్డ్ అవుతుంది.",
    "hi": "यह क्लिनिक की AI असिस्टेंट है. आपके अपॉइंटमेंट के लिए यह कॉल रिकॉर्ड की जा रही है जी.",
    "ta": "இது கிளினிக் AI அசிஸ்டன்ட்ங்க. உங்க அப்பாயிண்ட்மென்ட் ப்ராசஸ் பண்ண இந்த கால் ரெக்கார்ட் செய்யப்படுதுங்க.",
    "kn": "ಇದು ಕ್ಲಿನಿಕ್ AI ಅಸಿಸ್ಟೆಂಟ್ ರೀ. ನಿಮ್ಮ ಅಪಾಯಿಂಟ್‌ಮೆಂಟ್ ಪ್ರೊಸೆಸ್ ಮಾಡೋಕೆ ಈ ಕಾಲ್ ರೆಕಾರ್ಡ್ ಆಗ್ತಿದೆ ರೀ.",
    "mr": "हे क्लिनिकचं AI असिस्टंट आहे. तुमच्या अपॉइंटमेंटसाठी हा कॉल रेकॉर्ड केला जात आहे.",
    "en": "This is the clinic AI assistant. This call is processed for your appointment.",
}

_FALLBACK_DISCLOSURE = "en"


def build_disclosure_utterance(language: str = "te") -> str:
    """Return a single, generalized disclosure line in the caller's active language."""
    code = (language or "").strip().lower()
    return DISCLOSURES.get(code, DISCLOSURES[_FALLBACK_DISCLOSURE])


def get_clinic_now(tz_identifier: str = "Asia/Kolkata") -> datetime:
    """Guarantee time accuracy in the clinic's local timezone."""
    return datetime.now(tz=zoneinfo.ZoneInfo(tz_identifier))


def build_date_context(now_local: datetime) -> str:
    """Give the model an explicit eight-day date table to eliminate LLM date arithmetic errors."""
    today = now_local.date()
    labels = {0: "today ", 1: "tomorrow "}
    rows = [
        f"  {labels.get(i, '')}{(today + timedelta(days=i)).strftime('%A')} "
        f"= {(today + timedelta(days=i)).isoformat()}"
        for i in range(8)
    ]
    table = "\n".join(rows)
    return (
        f"\n\nTODAY IS {now_local.strftime('%A, %d %B %Y')} ({today.isoformat()}), "
        f"current time {now_local.strftime('%H:%M')}.\n"
        "DATE LOOKUP — when the caller names a weekday, 'today', or 'tomorrow', "
        "use the EXACT date from this list. NEVER calculate a date yourself:\n"
        f"{table}\n"
        "Always pass booking_date as YYYY-MM-DD copied from this list. For a date "
        "further out than next week, count forward from the matching weekday above. "
        "Never announce a date the patient didn't ask about.\n"
        "SPEAK-CHECK: before SAYING any weekday together with a date ('Wednesday, "
        "July eight'), verify the pair against ONE row of the list above — if the "
        "pair is not a row, you are wrong. If the caller corrects your date or "
        "weekday, NEVER argue: re-read the list and use the row matching THEIR "
        "weekday."
    )


def build_system_prompt(
    clinic_name: str,
    doctors: list[DoctorContext],
    emergency_contact: str,
    plan: str,
    is_rebook: bool = False,
    cancelled_date: str | None = None,
    language: str = "te",
    clinic_address: str | None = None,
    faq: list[dict] | None = None,
    recording_active: bool = False,
    warmth: str = "standard",
    call_type: str = "inbound",
    tz_identifier: str = "Asia/Kolkata",
) -> str:
    """Render the grounded production prompt combined with the live date context."""
    now_local = get_clinic_now(tz_identifier)
    date_table = build_date_context(now_local)
    
    prompt = build_grounded_prompt(
        clinic_name=clinic_name,
        doctors=doctors,
        emergency_contact=emergency_contact,
        plan=plan,
        is_rebook=is_rebook,
        cancelled_date=cancelled_date,
        language=language,
        clinic_address=clinic_address,
        faq=faq,
        recording_active=recording_active,
        warmth=warmth,
        call_type=call_type,
    )
    
    return prompt + date_table
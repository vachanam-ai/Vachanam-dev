"""Public entry points and runtime date-table builder for Vachanam."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as dt_date
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
    # The authoritative sitting hours. {"0": [{"start": "09:00", "end": "12:00"},
    # {"start": "17:00", "end": "21:00"}], ...} — a doctor may sit SEVERAL
    # sessions a day, which working_hours_start/end cannot express.
    schedule: dict | None = None
    schedule_mode: str = "recurring"  # recurring | date_specific


# Generalized, privacy-safe disclosures per active language
DISCLOSURES: dict[str, str] = {
    "te": "ఇది క్లినిక్ AI అసిస్టెంట్ అండి. మీ అపాయింట్‌మెంట్ ప్రాసెస్ చేయడం కోసం ఈ కాల్ రికార్డ్ అవుతుంది.",
    "hi": "यह क्लिनिक की AI असिस्टेंट है. आपके अपॉइंटमेंट के लिए यह कॉल रिकॉर्ड की जा रही है जी.",
    "ta": "இது கிளினிக் AI அசிஸ்டன்ட்ங்க. உங்க அப்பாயிண்ட்மென்ட் ப்ராசஸ் பண்ண இந்த கால் ரெக்கார்ட் செய்யப்படுதுங்க.",
    "kn": "ಇದು ಕ್ಲಿನಿಕ್ AI ಅಸಿಸ್ಟೆಂಟ್ ರೀ. ನಿಮ್ಮ ಅಪಾಯಿಂಟ್‌ಮೆಂಟ್ ಪ್ರೊಸೆಸ್ ಮಾಡೋಕೆ ಈ ಕಾಲ್ ರೆಕಾರ್ಡ್ ಆಗ್ತಿದೆ ರೀ.",
    "ml": "ഇത് ക്ലിനിക്കിന്റെ AI അസിസ്റ്റന്റാണ്. നിങ്ങളുടെ അപ്പോയിന്റ്മെന്റിനായി ഈ കോൾ റെക്കോർഡ് ചെയ്യുന്നു.",
    "bn": "এটি ক্লিনিকের AI অ্যাসিস্ট্যান্ট। আপনার অ্যাপয়েন্টমেন্টের জন্য এই কলটি রেকর্ড করা হচ্ছে।",
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


_DATE_LOOKAHEAD_DAYS = 35


def build_date_table(today: dt_date) -> str:
    """The exact five-week date table, WITHOUT the wall clock.

    Split out from build_date_context so the table can ride in the model
    INSTRUCTIONS while the clock stays out of them. Both halves have to live
    where they do:

    * The table must be in the instructions, because instructions are resent
      on every inference and are never trimmed. Seeded into chat history
      instead, it is the FIRST thing the window drops on a long call — which
      is how a live call on 2026-08-07 announced "11 August 2026" at turn 28
      (and, before it, "2 December 2024").
    * The clock must NOT be in the instructions, because the prompt cache is
      keyed on their digest. A HH:MM that ticks every minute would mint a new
      CachedContent entry every minute and the cache would never warm.

    Stable for a whole calendar day, so the cache re-keys once at midnight —
    which is exactly right: a stale date can then never be served from cache.
    """
    labels = {0: "today ", 1: "tomorrow "}
    rows = [
        f"  {labels.get(i, '')}{(today + timedelta(days=i)).strftime('%A')} "
        f"= {(today + timedelta(days=i)).isoformat()}"
        for i in range(_DATE_LOOKAHEAD_DAYS)
    ]
    table = "\n".join(rows)
    return (
        f"\n\nTODAY IS {today.strftime('%A, %d %B %Y')} ({today.isoformat()}).\n"
        "DATE LOOKUP — when the caller names a weekday, 'today', or 'tomorrow', "
        "use the EXACT date from this list. NEVER calculate a date yourself:\n"
        f"{table}\n"
        "Always pass booking_date as YYYY-MM-DD copied from this list. If the caller "
        "asks for a date beyond this list, ask for an exact calendar date instead of "
        "calculating or inventing an ISO date. "
        "Never announce a date the patient didn't ask about.\n"
        "SPEAK-CHECK: before SAYING any weekday together with a date ('Wednesday, "
        "July eight'), verify the pair against ONE row of the list above — if the "
        "pair is not a row, you are wrong. If the caller corrects your date or "
        "weekday, NEVER argue: re-read the list and use the row matching THEIR "
        "weekday."
    )


def build_date_context(now_local: datetime) -> str:
    """The date table plus the wall clock — for the per-call runtime block."""
    return (
        build_date_table(now_local.date())
        + f"\nRight now the current time {now_local.strftime('%H:%M')}."
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
    
    # Keep the ordered contract's language lock as the actual final authority.
    # An English date table appended after it used to pull non-English calls
    # back toward English mid-conversation.
    return date_table + prompt

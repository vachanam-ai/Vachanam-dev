"""Stable public entry points for Vachanam's production voice prompt."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

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


# DPDP s.5 disclosure. The call site sanitizes this before TTS.
DISCLOSURE_TELUGU = (
    "idi AI assistant. mee appointment kosam mee peru mariyu phone number vadatamu."
)
DISCLOSURE_ENGLISH = (
    "This is an AI assistant. We collect your name and phone for your appointment."
)
DISCLOSURE_HINDI = (
    "yeh AI assistant hai. aapke appointment ke liye aapka naam aur phone number lenge."
)
DISCLOSURE_UTTERANCE = (
    f"{DISCLOSURE_TELUGU} {DISCLOSURE_ENGLISH} {DISCLOSURE_HINDI}"
)


def build_disclosure_utterance() -> str:
    """Return the disclosure; the call site owns the TTS-sanitization boundary."""
    return DISCLOSURE_UTTERANCE


def build_date_context(now_local) -> str:
    """Give the model an explicit eight-day table instead of date arithmetic."""
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
        "weekday. (Live failure: agent insisted 'this Wednesday is July ninth' "
        "while the list said Wednesday = July 8.)"
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
) -> str:
    """Render the sole priority-ordered, grounded production prompt."""
    return build_grounded_prompt(
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
    )

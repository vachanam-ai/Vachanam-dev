"""WhatsApp template payload builders (spec 2026-07-13, plan T4).

Pure functions: each returns (template_name, lang, body_params, buttons).
Template names + {{n}} slot order MUST match the Meta-registered templates in
docs/runbooks/META_TEMPLATES.md. Day-1 languages: te + en — a patient whose
preferred language is anything else gets en (template must exist in the sent
language or Meta rejects the send).

Button-id grammar (consumed by the T5 webhook dispatcher):
    rs:{token_id}              reschedule this booking
    cx:{token_id}              cancel this booking
    rate:{token_id}:{1-5}      post-visit rating score
    slot:{token_id}:{date}:{HH:MM|none}   picked replacement slot

RULE 9: params carry logistics only — clinic, doctor, date/time, token,
address. Never complaint or visit-note text.
"""
from __future__ import annotations

from datetime import date, time
from urllib.parse import quote

_DAY1_LANGS = {"te", "en"}


def template_lang(preferred: str | None) -> str:
    """Language the template is sent in (te/en day 1, everyone else en)."""
    p = (preferred or "").lower().strip()
    return p if p in _DAY1_LANGS else "en"


def _when(booking_date: date, appointment_time: time | None,
          token_number: int | None) -> str:
    d = booking_date.strftime("%d %B")
    if appointment_time is not None:
        return f"{d}, {appointment_time.strftime('%I:%M %p').lstrip('0')}"
    return f"{d}, token {token_number}" if token_number else d


def maps_link(address: str | None) -> str:
    return f"https://maps.google.com/?q={quote(address)}" if address else ""


def booking_confirm(
    *, clinic: str, doctor: str, booking_date: date,
    appointment_time: time | None, token_number: int | None,
    address: str | None, token_id: str, lang: str,
) -> tuple[str, str, list[str], list[dict]]:
    """{{1}} clinic · {{2}} doctor · {{3}} when · {{4}} location line."""
    loc = maps_link(address) or "the clinic"
    return (
        "booking_confirm",
        lang,
        [clinic, doctor, _when(booking_date, appointment_time, token_number), loc],
        [
            {"id": f"rs:{token_id}", "title": "Reschedule"},
            {"id": f"cx:{token_id}", "title": "Cancel"},
        ],
    )


def appt_reminder(
    *, doctor: str, appointment_time: time | None, token_number: int | None,
    token_id: str, lang: str,
) -> tuple[str, str, list[str], list[dict]]:
    """{{1}} doctor · {{2}} time-or-token."""
    when = (
        appointment_time.strftime("%I:%M %p").lstrip("0")
        if appointment_time else f"token {token_number}"
    )
    return (
        "appt_reminder",
        lang,
        [doctor, when],
        [
            {"id": f"rs:{token_id}", "title": "Reschedule"},
            {"id": f"cx:{token_id}", "title": "Cancel"},
        ],
    )


def rating_ask(*, clinic: str, token_id: str, lang: str,
               ) -> tuple[str, str, list[str], list[dict]]:
    """{{1}} clinic. Quick replies = 1..5 stars (Meta caps quick replies; the
    registered template carries exactly these five)."""
    return (
        "rating_ask",
        lang,
        [clinic],
        [{"id": f"rate:{token_id}:{n}", "title": f"{n} ⭐"} for n in (1, 2, 3, 4, 5)],
    )


def leave_rebook(*, doctor: str, on_date: date, token_id: str, lang: str,
                 ) -> tuple[str, str, list[str], list[dict]]:
    """{{1}} doctor · {{2}} date."""
    return (
        "leave_rebook",
        lang,
        [doctor, on_date.strftime("%d %B")],
        [{"id": f"rs:{token_id}", "title": "Reschedule"}],
    )

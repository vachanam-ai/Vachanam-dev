"""F5 (plan Task 6.3): build the deterministic post-tool confirmation line.

Pure text builder — no LiveKit, no DB. Returns the native-script line for a
successful booking/reschedule/cancel, or None when the language has no
template yet (that language keeps the LLM-spoken path) or inputs are missing.
Date/time wording reuses the exact helpers the outbound greetings already use
(telugu_date/telugu_time for te, strftime for the rest) — no new date logic.
"""
from __future__ import annotations

from datetime import date as date_cls
from datetime import time as time_cls

from agent.i18n.lines import get_lines
from agent.services.telugu_dates import telugu_date, telugu_time

_KIND_FIELD = {
    "booked_token": "confirm_booked_token",
    "booked_slot": "confirm_booked_slot",
    "resched_slot": "confirm_resched_slot",
    "resched_token": "confirm_resched_token",
    "cancelled": "confirm_cancelled",
}


def _spoken_date(d: date_cls, lang_code: str) -> str:
    return telugu_date(d) if lang_code == "te" else d.strftime("%d %B").lstrip("0")


def _spoken_time(t: time_cls, lang_code: str) -> str:
    return telugu_time(t) if lang_code == "te" else t.strftime("%I:%M %p").lstrip("0")


def build_confirm_text(
    lang_code: str,
    kind: str,
    *,
    token: int | None = None,
    date_: date_cls | None = None,
    time_: time_cls | None = None,
) -> str | None:
    field = _KIND_FIELD.get(kind)
    if field is None:
        return None
    template = getattr(get_lines(lang_code), field, "")
    if not template:
        return None
    fmt: dict[str, str] = {}
    if "{token}" in template:
        if token is None:
            return None  # required value missing → let the LLM speak instead
        fmt["token"] = str(token)
    if "{date}" in template:
        if date_ is None:
            return None
        fmt["date"] = _spoken_date(date_, lang_code)
    if "{time}" in template:
        if time_ is None:
            return None
        fmt["time"] = _spoken_time(time_, lang_code)
    return template.format(**fmt)

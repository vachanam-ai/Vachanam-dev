"""Deterministic post-tool confirmation speech.

Successful booking mutations have no creative work left for the LLM. This
builder turns their verified result into a short native-script line so the
voice can answer immediately after the write, without a second model pass.
"""
from __future__ import annotations

from datetime import date as date_cls
from datetime import time as time_cls

from agent.i18n.lines import LINES, get_lines
from agent.services.telugu_dates import telugu_date, telugu_time

_KIND_FIELD = {
    "booked_token": "confirm_booked_token",
    "booked_slot": "confirm_booked_slot",
    "resched_slot": "confirm_resched_slot",
    "resched_token": "confirm_resched_token",
    "cancelled": "confirm_cancelled",
}


def _spoken_date(value: date_cls, lang_code: str) -> str:
    return (
        telugu_date(value)
        if lang_code == "te"
        else value.strftime("%d %B").lstrip("0")
    )


def _spoken_time(value: time_cls, lang_code: str) -> str:
    return (
        telugu_time(value)
        if lang_code == "te"
        else value.strftime("%I:%M %p").lstrip("0")
    )


def build_confirm_text(
    lang_code: str,
    kind: str,
    *,
    token: int | None = None,
    date_: date_cls | None = None,
    time_: time_cls | None = None,
) -> str | None:
    lang_code = (lang_code or "").lower().strip()
    if lang_code not in LINES:
        return None
    field = _KIND_FIELD.get(kind)
    if field is None:
        return None
    template = getattr(get_lines(lang_code), field, "")
    if not template:
        return None

    values: dict[str, str] = {}
    if "{token}" in template:
        if token is None:
            return None
        values["token"] = str(token)
    if "{date}" in template:
        if date_ is None:
            return None
        values["date"] = _spoken_date(date_, lang_code)
    if "{time}" in template:
        if time_ is None:
            return None
        values["time"] = _spoken_time(time_, lang_code)
    return template.format(**values)

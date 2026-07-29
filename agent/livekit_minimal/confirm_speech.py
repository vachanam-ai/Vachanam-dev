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
        # A verified write must never fall back to a creative LLM outcome.
        # Until a native-reviewed template exists, deterministic English is
        # safer than a fluent contradiction such as "I couldn't book" after a
        # successful commit.
        template = getattr(get_lines("en"), field, "")

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
    text = template.format(**values)
    if kind in {"booked_token", "booked_slot"}:
        anything_else = getattr(get_lines(lang_code), "anything_else", "")
        if not anything_else:
            anything_else = get_lines("en").anything_else
        text = f"{text} {anything_else}"
    return text


def build_exact_availability_text(
    lang_code: str, *, date_: date_cls, time_: time_cls
) -> str | None:
    """Speak only an exact positive DB result; ambiguous windows stay with the LLM."""
    lang = (lang_code or "").lower().strip()
    values = {
        "date": _spoken_date(date_, lang),
        "time": _spoken_time(time_, lang),
    }
    templates = {
        "te": "[happily] {date}, {time}కి డాక్టర్ గారు అందుబాటులో ఉన్నారండి. పేషెంట్ పేరు చెప్పండి.",
        "en": "[happily] The doctor is available on {date} at {time}. May I have the patient's name?",
        "hi": "[happily] डॉक्टर {date} को {time} बजे उपलब्ध हैं। मरीज का नाम बताइए।",
    }
    template = templates.get(lang)
    return template.format(**values) if template else None


def build_queue_status_text(lang_code: str, entry: dict) -> str | None:
    """Render one caller-owned queue row without a creative model pass."""
    lang = (lang_code or "").lower().strip()
    token = entry.get("token_number")
    ahead = entry.get("patients_ahead")
    if token is None or ahead is None:
        return None
    now = entry.get("now_serving")
    if now is None:
        templates = {
            "te": "[softly] మీ టోకెన్ నంబర్ {token}. క్యూ ఇంకా మొదలవలేదండి.",
            "en": "[softly] Your token number is {token}. The queue has not started yet.",
            "hi": "[softly] आपका टोकन नंबर {token} है। कतार अभी शुरू नहीं हुई है।",
        }
        template = templates.get(lang)
        return template.format(token=token) if template else None
    templates = {
        "te": "[happily] ప్రస్తుతం టోకెన్ నంబర్ {now} నడుస్తోంది. మీది {token}. మీ ముందు {ahead} మంది ఉన్నారు.",
        "en": "[happily] Token {now} is being seen now. Yours is {token}, with {ahead} ahead of you.",
        "hi": "[happily] अभी टोकन नंबर {now} चल रहा है। आपका {token} है और आपसे पहले {ahead} लोग हैं।",
    }
    template = templates.get(lang)
    return template.format(now=now, token=token, ahead=ahead) if template else None

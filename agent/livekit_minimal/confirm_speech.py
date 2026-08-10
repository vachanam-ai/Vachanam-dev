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

_BOOKING_HELP = {
    'te': 'ఇంకేమైనా సహాయం కావాలా అండి?',
    'en': 'Is there anything else I can help you with?',
    'hi': 'और कुछ मदद चाहिए जी?',
    'ta': 'வேற ஏதாவது உதவி வேணுமாங்?',
    'kn': 'ಇನ್ನೇನಾದರೂ ಸಹಾಯ ಬೇಕಾ?',
    'mr': 'आणखी काही मदत हवी आहे का?',
}

_CLINIC_QUESTION_ACK = {
    'te': 'సరే అండి. ఈ ప్రశ్నను నమోదు చేశాను. క్లినిక్ డాక్టర్‌ని అడిగి మీకు కాల్ చేస్తారు.',
    'en': 'All right. I have noted this question. The clinic will check with the doctor and call you back.',
    'hi': 'ठीक है जी। मैंने यह सवाल दर्ज कर लिया है। क्लिनिक डॉक्टर से पूछकर आपको वापस कॉल करेगा।',
    'ta': 'சரி. இந்தக் கேள்வியை பதிவு செய்துவிட்டேன். கிளினிக் மருத்துவரிடம் கேட்டுவிட்டு உங்களைத் திரும்ப அழைக்கும்.',
    'kn': 'ಸರಿ. ಈ ಪ್ರಶ್ನೆಯನ್ನು ದಾಖಲಿಸಿದ್ದೇನೆ. ಕ್ಲಿನಿಕ್ ವೈದ್ಯರನ್ನು ಕೇಳಿ ನಿಮಗೆ ಮತ್ತೆ ಕರೆ ಮಾಡುತ್ತದೆ.',
    'mr': 'ठीक आहे. हा प्रश्न नोंदवला आहे. क्लिनिक डॉक्टरांना विचारून तुम्हाला परत कॉल करेल.',
    'bn': 'ঠিক আছে। প্রশ্নটি নথিভুক্ত করেছি। ক্লিনিক ডাক্তারকে জিজ্ঞেস করে আপনাকে আবার ফোন করবে।',
    'ml': 'ശരി. ഈ ചോദ്യം രേഖപ്പെടുത്തിയിട്ടുണ്ട്. ക്ലിനിക്ക് ഡോക്ടറോട് ചോദിച്ചിട്ട് നിങ്ങളെ തിരികെ വിളിക്കും.',
}


def build_clinic_question_ack(lang_code: str) -> str:
    """Verified acknowledgement after a clinic question is committed."""
    return _CLINIC_QUESTION_ACK.get(
        (lang_code or '').lower().strip(), _CLINIC_QUESTION_ACK['en']
    )


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
    spoken = template.format(**values)
    if kind in {'booked_token', 'booked_slot'}:
        help_line = _BOOKING_HELP.get(lang_code)
        if help_line:
            spoken = f'{spoken} {help_line}'
    return spoken

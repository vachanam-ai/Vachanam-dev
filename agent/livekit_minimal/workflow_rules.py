"""Deterministic speech for safety-critical workflow outcomes.

The language model never interprets these results. Known refusals are stated
as refusals; ambiguous database outcomes are explicitly left unclaimed.
"""
from __future__ import annotations

import re


def build_mutation_failure_text(
    lang_code: str,
    operation: str,
    result: dict,
) -> str:
    lang = (lang_code or "").lower().strip()
    code = str(result.get("error") or result.get("reason") or "unknown")
    known_unavailable = {
        "full",
        "slot_full",
        "past_slot",
        "off_grid_time",
        "appointment_time_required",
        "schedule_not_configured",
        "not_bookable",
    }
    not_found = code == "booking_not_found" or code.startswith(
        ("not_cancellable_", "not_reschedulable_")
    )
    already_booked = code == "already_booked"
    uncertain = (
        "unverified" in code
        or "reconciliation" in code
        or code in {
            "cancellation_failed",
            "old_booking_not_cancelled",
            "booking_system_unavailable",
            "unknown",
        }
    )
    if code in known_unavailable:
        key = "unavailable"
    elif not_found:
        key = "not_found"
    elif already_booked:
        key = "already_booked"
    elif uncertain:
        key = "uncertain"
    else:
        key = "refused"

    labels = {
        "book": {"en": "the booking", "te": "బుకింగ్", "hi": "बुकिंग"},
        "cancel": {"en": "the cancellation", "te": "క్యాన్సిలేషన్", "hi": "कैंसलेशन"},
        "reschedule": {"en": "the reschedule", "te": "రీషెడ్యూల్", "hi": "रीशेड्यूल"},
        "reserve": {"en": "that slot", "te": "ఆ స్లాట్", "hi": "वह स्लॉट"},
    }
    label_set = labels.get(operation, labels["book"])
    label = label_set.get(lang, label_set["en"])
    messages = {
        "en": {
            "unavailable": "[softly] That date or time could not be reserved. Please choose another date or time.",
            "not_found": "[softly] I could not find that appointment under this caller number, so I did not change anything.",
            "already_booked": "[softly] This caller number already has an appointment there. Shall I help move the existing appointment?",
            "uncertain": f"[softly] I could not verify {label}'s final status, so I will not guess. Shall I check your appointments?",
            "refused": f"[softly] {label.capitalize()} was not accepted, so I did not announce it as completed. Shall we try again?",
        },
        "te": {
            "unavailable": "[softly] ఆ తేదీ లేదా టైమ్‌కి స్లాట్ రిజర్వ్ కాలేదండి. ఇంకో తేదీ లేదా టైమ్ చెప్పండి.",
            "not_found": "[softly] ఈ కాలర్ నంబర్‌లో ఆ అపాయింట్‌మెంట్ కనిపించలేదండి. అందుకే ఏ మార్పూ చేయలేదు.",
            "already_booked": "[softly] ఈ కాలర్ నంబర్‌లో ఇప్పటికే అపాయింట్‌మెంట్ ఉందండి. దానిని మార్చనా?",
            "uncertain": f"[softly] {label} చివరి స్థితి ఇప్పుడు కన్ఫర్మ్ చేయలేకపోయాను. నేను ఊహించి చెప్పను. మీ అపాయింట్‌మెంట్లు చెక్ చేయనా?",
            "refused": f"[softly] {label} పూర్తయిందని నిర్ధారణ కాలేదండి. అందుకే పూర్తయిందని చెప్పను. మళ్లీ ప్రయత్నించనా?",
        },
        "hi": {
            "unavailable": "[softly] उस तारीख या समय का स्लॉट रिज़र्व नहीं हुआ। कृपया कोई दूसरा समय बताइए।",
            "not_found": "[softly] इस कॉलर नंबर पर वह अपॉइंटमेंट नहीं मिला, इसलिए मैंने कोई बदलाव नहीं किया।",
            "already_booked": "[softly] इस कॉलर नंबर पर पहले से अपॉइंटमेंट है। क्या मैं उसी को बदल दूँ?",
            "uncertain": f"[softly] {label} की अंतिम स्थिति अभी कन्फ़र्म नहीं हो पाई। मैं अनुमान नहीं लगाऊँगी। क्या मैं आपके अपॉइंटमेंट जाँचूँ?",
            "refused": f"[softly] {label} पूरा होने की पुष्टि नहीं हुई, इसलिए मैं इसे पूरा नहीं बताऊँगी। फिर से कोशिश करें?",
        },
    }
    return messages.get(lang, messages["en"])[key]


def build_read_failure_text(lang_code: str) -> str:
    """Fixed warm line for when a read's DB connection FAILS outright (outage /
    pooler breaker), not a data condition. Offers a retry rather than leaking a
    technical error. Same wording already used by the grounded-turn read-failure
    handler, kept here so tool-level guards reuse it (2026-07-31)."""
    messages = {
        "en": "[softly] Sorry, I could not check that just now. Shall I try again?",
        "te": "[softly] క్షమించండి, ఇప్పుడది కరెక్ట్‌గా చెక్ చేయలేకపోయాను. మళ్ళీ చెక్ చేయనా?",
        "hi": "[softly] माफ़ कीजिए, मैं अभी यह सही तरह जाँच नहीं पाई। फिर से जाँचूँ?",
    }
    return messages.get((lang_code or "").lower(), messages["en"])


_AVAIL_TIME_RE = re.compile(r"\d{1,2}:\d{2}\s*[AP]M", re.IGNORECASE)


def _nearest_free_times(raw: str) -> str:
    """Pull the concrete next free clock-times out of a grounded availability
    string, so the fast-path can OFFER them instead of a dead-end "shall I
    check another time?" (which made a caller loop — Vinay live 2026-07-31).

    Only reads the segment AFTER the nearest/upcoming marker so the requested
    (unavailable) time in the sentence is never mistaken for a free one."""
    for marker in (
        "Next upcoming free times:",
        "NEAREST free times to their request:",
    ):
        idx = raw.find(marker)
        if idx == -1:
            continue
        segment = raw[idx + len(marker):].split(".")[0]
        seen: list[str] = []
        for match in _AVAIL_TIME_RE.findall(segment):
            normalized = re.sub(r"\s+", " ", match).strip().upper()
            if normalized not in seen:
                seen.append(normalized)
        if seen:
            return " or ".join(seen[:2])
    return ""


def build_exact_availability_failure_text(
    lang_code: str,
    availability: str,
) -> str:
    """Fail-closed wording for an exact-time DB result that is not positive."""
    raw = availability or ""
    if "SCHEDULE NOT PUBLISHED" in raw or "schedule is not configured" in raw:
        key = "unpublished"
    elif "REQUESTED TIME PASSED" in raw:
        key = "past_time"
    elif "on leave" in raw or "unavailable" in raw:
        key = "leave"
    elif "NOT free" in raw or "fully booked" in raw:
        key = "not_free"
    else:
        key = "unverified"

    # For the two cases where the DB handed us concrete upcoming slots, speak
    # them — that is what breaks the "shall I check another time?" loop.
    nearest = _nearest_free_times(raw) if key in ("past_time", "not_free") else ""

    messages = {
        "en": {
            "unpublished": "[softly] The doctor's timing for that day is not confirmed yet.",
            "leave": "[softly] The doctor is not available that day. Shall I check another day?",
            "not_free": "[softly] That exact time is not free. Shall I check another time?",
            "past_time": "[softly] That time has already passed today. Shall I check a later time or another day?",
            "unverified": "[softly] I could not verify that exact time, so I will not guess. Shall I check again?",
        },
        "te": {
            "unpublished": "[softly] ఆ రోజు డాక్టర్ టైమింగ్ ఇంకా కన్ఫర్మ్ కాలేదండి.",
            "leave": "[softly] ఆ రోజు డాక్టర్ అందుబాటులో లేరండి. ఇంకో రోజు చెక్ చేయనా?",
            "not_free": "[softly] ఆ టైమ్‌కి ఖాళీ లేదండి. ఇంకో టైమ్ చెక్ చేయనా?",
            "past_time": "[softly] ఆ టైమ్ ఇవాళ అయిపోయిందండి. తర్వాత టైమ్ చూడనా, లేక వేరే రోజు చూడనా?",
            "unverified": "[softly] ఆ టైమ్‌ని ఇప్పుడు కన్ఫర్మ్ చేయలేకపోయాను. నేను ఊహించి చెప్పను. మళ్లీ చెక్ చేయనా?",
        },
        "hi": {
            "unpublished": "[softly] उस दिन डॉक्टर का समय अभी तय नहीं हुआ है।",
            "leave": "[softly] डॉक्टर उस दिन उपलब्ध नहीं हैं। कोई और दिन जाँचूँ?",
            "not_free": "[softly] उस समय जगह खाली नहीं है। कोई और समय जाँचूँ?",
            "past_time": "[softly] वह समय आज निकल चुका है। बाद का कोई समय देखूँ या कोई और दिन?",
            "unverified": "[softly] उस समय की पुष्टि नहीं हुई। मैं अनुमान नहीं लगाऊँगी। फिर से जाँचूँ?",
        },
    }
    # When we have concrete upcoming slots, replace the trailing question with a
    # direct offer of those real times.
    offer = {
        "en": "[softly] That time is not free. The next free times are {t}. Shall I book one?",
        "te": "[softly] ఆ టైమ్ ఖాళీ లేదండి. తర్వాత ఖాళీ ఉన్న టైమ్‌లు {t}. ఏదైనా ఒకటి బుక్ చేయనా?",
        "hi": "[softly] वह समय खाली नहीं है। अगले खाली समय {t} हैं। कोई एक बुक करूँ?",
    }
    lang = (lang_code or "").lower()
    if nearest:
        return offer.get(lang, offer["en"]).format(t=nearest)
    return messages.get(lang, messages["en"])[key]

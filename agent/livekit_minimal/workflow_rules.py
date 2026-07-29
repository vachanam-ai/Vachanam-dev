"""Deterministic speech for safety-critical workflow outcomes.

The language model never interprets these results. Known refusals are stated
as refusals; ambiguous database outcomes are explicitly left unclaimed.
"""
from __future__ import annotations


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
            "uncertain": f"[softly] {label} చివరి స్థితి డేటాబేస్‌లో నిర్ధారించలేకపోయాను. నేను ఊహించి చెప్పను. మీ అపాయింట్‌మెంట్లు చెక్ చేయనా?",
            "refused": f"[softly] {label} పూర్తయిందని నిర్ధారణ కాలేదండి. అందుకే పూర్తయిందని చెప్పను. మళ్లీ ప్రయత్నించనా?",
        },
        "hi": {
            "unavailable": "[softly] उस तारीख या समय का स्लॉट रिज़र्व नहीं हुआ। कृपया कोई दूसरा समय बताइए।",
            "not_found": "[softly] इस कॉलर नंबर पर वह अपॉइंटमेंट नहीं मिला, इसलिए मैंने कोई बदलाव नहीं किया।",
            "already_booked": "[softly] इस कॉलर नंबर पर पहले से अपॉइंटमेंट है। क्या मैं उसी को बदल दूँ?",
            "uncertain": f"[softly] डेटाबेस में {label} की अंतिम स्थिति सत्यापित नहीं हुई। मैं अनुमान नहीं लगाऊँगी। क्या मैं आपके अपॉइंटमेंट जाँचूँ?",
            "refused": f"[softly] {label} पूरा होने की पुष्टि नहीं हुई, इसलिए मैं इसे पूरा नहीं बताऊँगी। फिर से कोशिश करें?",
        },
    }
    return messages.get(lang, messages["en"])[key]


def build_exact_availability_failure_text(
    lang_code: str,
    availability: str,
) -> str:
    """Fail-closed wording for an exact-time DB result that is not positive."""
    raw = availability or ""
    if "SCHEDULE NOT PUBLISHED" in raw or "schedule is not configured" in raw:
        key = "unpublished"
    elif "on leave" in raw or "unavailable" in raw:
        key = "leave"
    elif "NOT free" in raw or "fully booked" in raw:
        key = "not_free"
    else:
        key = "unverified"
    messages = {
        "en": {
            "unpublished": "[softly] The doctor's timing for that day is not confirmed yet.",
            "leave": "[softly] The doctor is not available that day. Shall I check another day?",
            "not_free": "[softly] That exact time is not free. Shall I check another time?",
            "unverified": "[softly] I could not verify that exact time, so I will not guess. Shall I check again?",
        },
        "te": {
            "unpublished": "[softly] ఆ రోజు డాక్టర్ టైమింగ్ ఇంకా కన్ఫర్మ్ కాలేదండి.",
            "leave": "[softly] ఆ రోజు డాక్టర్ అందుబాటులో లేరండి. ఇంకో రోజు చెక్ చేయనా?",
            "not_free": "[softly] ఆ టైమ్‌కి ఖాళీ లేదండి. ఇంకో టైమ్ చెక్ చేయనా?",
            "unverified": "[softly] ఆ టైమ్‌ని డేటాబేస్‌లో నిర్ధారించలేకపోయాను. నేను ఊహించి చెప్పను. మళ్లీ చెక్ చేయనా?",
        },
        "hi": {
            "unpublished": "[softly] उस दिन डॉक्टर का समय अभी तय नहीं हुआ है।",
            "leave": "[softly] डॉक्टर उस दिन उपलब्ध नहीं हैं। कोई और दिन जाँचूँ?",
            "not_free": "[softly] उस समय जगह खाली नहीं है। कोई और समय जाँचूँ?",
            "unverified": "[softly] उस समय की पुष्टि नहीं हुई। मैं अनुमान नहीं लगाऊँगी। फिर से जाँचूँ?",
        },
    }
    return messages.get((lang_code or "").lower(), messages["en"])[key]

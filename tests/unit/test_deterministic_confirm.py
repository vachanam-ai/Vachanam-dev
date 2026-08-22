"""Verified booking outcomes bypass the redundant second LLM pass."""
from datetime import date, time
from pathlib import Path
import re

from agent.i18n.lines import LINES
from agent.livekit_minimal.confirm_speech import (
    _spoken_date,
    _spoken_time,
    build_booking_confirmation_question,
    build_booking_lookup_text,
    build_cancellation_confirmation_question,
    build_clinic_question_ack,
    build_confirm_text,
    build_no_booking_found_text,
    build_read_failure_text,
)

D = date(2026, 7, 25)
T = time(10, 30)


def test_telugu_booking_and_reschedule_use_punctuality_wording():
    token = build_confirm_text("te", "booked_token", token=13, date_=D)
    slot = build_confirm_text("te", "booked_slot", date_=D, time_=T)
    moved = build_confirm_text("te", "resched_slot", date_=D, time_=T)
    assert token and "13" in token and "టైంకి రండి" in token
    assert slot and "టైంకి రండి" in slot and "13" not in slot
    assert moved and "టైంకి రండి" in moved and "పాతది" in moved


def test_booking_confirmation_offers_help_once():
    for code in LINES:
        text = build_confirm_text(code, 'booked_slot', date_=D, time_=T)
        assert text and text.rstrip().endswith('?'), f'{code}: {text}'
    assert 'ఇంకేమైనా సహాయం కావాలా అండి?' in build_confirm_text(
        'te', 'booked_slot', date_=D, time_=T
    )


def test_booking_receipt_and_lookup_name_the_patient_and_doctor():
    for code in LINES:
        receipt = build_confirm_text(
            code,
            "booked_slot",
            date_=D,
            time_=T,
            patient_name="Asha Test",
            doctor_name="Dr Rao",
        )
        lookup = build_booking_lookup_text(
            code,
            {
                "patient_name": "Asha Test",
                "doctor": "Dr Rao",
                "date": D.isoformat(),
                "time": T.isoformat(),
                "booking_type": "appointment",
                "status": "confirmed",
            },
        )
        for text in (receipt, lookup):
            assert text
            assert text.count("Asha Test") == 1
            assert text.count("Dr Rao") == 1


def test_cancel_is_not_happy_and_does_not_say_come_on_time():
    text = build_confirm_text("te", "cancelled")
    assert text and "[softly]" in text
    assert "[happily]" not in text and "టైంకి" not in text


def test_unsupported_template_or_missing_required_value_falls_back():
    assert build_confirm_text("or", "booked_token", token=3, date_=D) is None
    assert build_confirm_text("te", "booked_token", date_=D) is None
    assert build_confirm_text("te", "unknown", token=1) is None


def test_every_defined_template_formats_without_placeholders():
    for lines in LINES.values():
        for field, values in (
            ("confirm_booked_token", {"token": 12, "date": "x"}),
            ("confirm_booked_slot", {"date": "x", "time": "y"}),
            ("confirm_resched_slot", {"date": "x", "time": "y"}),
            ("confirm_resched_token", {"token": 12, "date": "x"}),
            ("confirm_cancelled", {}),
        ):
            template = getattr(lines, field)
            if template:
                assert "{" not in template.format(**values)


def test_every_exposed_language_has_all_mutation_confirmations():
    for code, lines in LINES.items():
        for field in (
            "confirm_booked_token",
            "confirm_booked_slot",
            "confirm_resched_slot",
            "confirm_resched_token",
            "confirm_cancelled",
        ):
            assert getattr(lines, field).strip(), f"{code}.{field} is empty"


def test_malayalam_and_bengali_mutation_confirmations_render_deterministically():
    for code in ("ml", "bn"):
        rendered = (
            build_confirm_text(code, "booked_token", token=12, date_=D),
            build_confirm_text(code, "booked_slot", date_=D, time_=T),
            build_confirm_text(code, "resched_slot", date_=D, time_=T),
            build_confirm_text(code, "resched_token", token=12, date_=D),
            build_confirm_text(code, "cancelled"),
        )
        assert all(text and "{" not in text for text in rendered)


def test_all_language_appointment_speech_is_complete_localized_and_not_doubled():
    english_month = re.compile(
        r"\b(?:January|February|March|April|May|June|July|August|"
        r"September|October|November|December)\b",
        re.IGNORECASE,
    )
    am_pm = re.compile(r"(?<![A-Za-z])(?:A\.?\s*M\.?|P\.?\s*M\.?)(?![A-Za-z])", re.I)
    doubled_suffixes = {
        "te": ("కికి", "కి కి"),
        "en": ("AM AM", "PM PM", "at at"),
        "hi": ("बजे बजे",),
        "ta": ("மணிக்குக்கு", "மணிக்கு மணிக்கு"),
        "kn": ("ಕ್ಕೆಕ್ಕೆ", "ಕ್ಕೆ ಕ್ಕೆ"),
        "ml": ("മണിക്ക്ന്", "മണിക്ക് മണിക്കാണ്", "മണിക്ക് മണിക്ക്"),
        "mr": ("वाजता वाजता",),
        "bn": ("টায়-এ", "টায় টায়"),
    }
    times = (time(9), time(10, 30), time(12), time(15, 45), time(17, 15), time(21))

    for code in LINES:
        no_booking = build_no_booking_found_text(code)
        assert no_booking.strip() and "{" not in no_booking and "}" not in no_booking
        for month in range(1, 13):
            day = date(2026, month, 21)
            spoken_date = _spoken_date(day, code)
            token_outputs = {
                "booked_token": build_confirm_text(
                    code, "booked_token", token=913, date_=day
                ),
                "resched_token": build_confirm_text(
                    code, "resched_token", token=913, date_=day
                ),
                "lookup_token": build_booking_lookup_text(
                    code,
                    {
                        "doctor": "Dr Rao",
                        "date": day.isoformat(),
                        "token_number": 913,
                        "booking_type": "token",
                        "status": "confirmed",
                    },
                ),
                "lookup_cancelled": build_booking_lookup_text(
                    code,
                    {
                        "doctor": "Dr Rao",
                        "date": day.isoformat(),
                        "status": "cancelled_by_clinic",
                    },
                ),
            }
            for label, text in token_outputs.items():
                assert text and text.strip(), f"{code}.{label} returned no speech"
                assert "{" not in text and "}" not in text, f"{code}.{label}: {text}"
                assert text.count(spoken_date) == 1, f"{code}.{label}: {text}"
                if label != "lookup_cancelled":
                    assert text.count("913") == 1, f"{code}.{label}: {text}"
                if label.startswith("lookup_"):
                    assert text.count("Dr Rao") == 1, f"{code}.{label}: {text}"
                if code != "en":
                    assert not english_month.search(text), f"{code}.{label}: {text}"
                    assert not am_pm.search(text), f"{code}.{label}: {text}"

            for value in times:
                spoken_time = _spoken_time(value, code)
                slot_outputs = {
                    "booked_slot": build_confirm_text(
                        code, "booked_slot", date_=day, time_=value
                    ),
                    "resched_slot": build_confirm_text(
                        code, "resched_slot", date_=day, time_=value
                    ),
                    "lookup_slot": build_booking_lookup_text(
                        code,
                        {
                            "doctor": "Dr Rao",
                            "date": day.isoformat(),
                            "time": value.isoformat(),
                            "status": "confirmed",
                        },
                    ),
                }
                for label, text in slot_outputs.items():
                    assert text and text.strip(), f"{code}.{label} returned no speech"
                    assert "{" not in text and "}" not in text, f"{code}.{label}: {text}"
                    assert text.count(spoken_date) == 1, f"{code}.{label}: {text}"
                    assert text.count(spoken_time) == 1, f"{code}.{label}: {text}"
                    if label == "lookup_slot":
                        assert text.count("Dr Rao") == 1, f"{code}.{label}: {text}"
                    assert not any(
                        bad.casefold() in text.casefold()
                        for bad in doubled_suffixes[code]
                    ), f"{code}.{label}: {text}"
                    if code != "en":
                        assert not english_month.search(text), f"{code}.{label}: {text}"
                        assert not am_pm.search(text), f"{code}.{label}: {text}"


def test_prewrite_booking_questions_bind_every_field_in_all_languages():
    english_month = re.compile(r"\bJuly\b", re.IGNORECASE)
    am_pm = re.compile(r"(?<![A-Za-z])(?:A\.?\s*M\.?|P\.?\s*M\.?)(?![A-Za-z])", re.I)

    for code in LINES:
        date_spoken = _spoken_date(D, code)
        time_spoken = _spoken_time(T, code)
        slot = build_booking_confirmation_question(
            code,
            booking_type="appointment",
            patient_name="  Asha   Test ",
            doctor_name=" Dr Rao ",
            date_=D,
            time_=T,
        )
        token = build_booking_confirmation_question(
            code,
            booking_type="token",
            patient_name="Asha Test",
            doctor_name="Dr Rao",
            date_=D,
            time_=T,
        )

        assert slot and token
        for text in (slot, token):
            assert text.count("?") == 1
            assert text.endswith("?")
            assert "{" not in text and "}" not in text
            assert text.count("Asha Test") == 1
            assert text.count("Dr Rao") == 1
            assert text.count(date_spoken) == 1
            if code != "en":
                assert not english_month.search(text)
                assert not am_pm.search(text)
        assert slot.count(time_spoken) == 1
        assert time_spoken not in token
        assert "913" not in token


def test_prewrite_cancellation_questions_bind_slot_or_token_in_all_languages():
    english_month = re.compile(r"\bJuly\b", re.IGNORECASE)
    am_pm = re.compile(r"(?<![A-Za-z])(?:A\.?\s*M\.?|P\.?\s*M\.?)(?![A-Za-z])", re.I)
    base = {
        "patient_name": "Asha Test",
        "doctor": "Dr Rao",
        "date": D.isoformat(),
    }

    for code in LINES:
        date_spoken = _spoken_date(D, code)
        time_spoken = _spoken_time(T, code)
        slot = build_cancellation_confirmation_question(
            code,
            {
                **base,
                "booking_type": "appointment",
                "time": T.isoformat(),
            },
        )
        token = build_cancellation_confirmation_question(
            code,
            {
                **base,
                "booking_type": "token",
                "token_number": 913,
            },
        )

        assert slot and token
        for text in (slot, token):
            assert text.count("?") == 1
            assert text.endswith("?")
            assert "{" not in text and "}" not in text
            assert text.count("Asha Test") == 1
            assert text.count("Dr Rao") == 1
            assert text.count(date_spoken) == 1
            if code != "en":
                assert not english_month.search(text)
                assert not am_pm.search(text)
        assert slot.count(time_spoken) == 1
        assert "913" not in slot
        assert time_spoken not in token
        assert token.count("913") == 1


def test_mutation_receipts_name_parties_for_reschedule_and_cancellation():
    for code in LINES:
        receipts = (
            build_confirm_text(
                code,
                "resched_slot",
                date_=D,
                time_=T,
                patient_name="Asha Test",
                doctor_name="Dr Rao",
            ),
            build_confirm_text(
                code,
                "resched_token",
                token=913,
                date_=D,
                patient_name="Asha Test",
                doctor_name="Dr Rao",
            ),
            build_confirm_text(
                code,
                "cancelled",
                patient_name="Asha Test",
                doctor_name="Dr Rao",
            ),
        )
        for text in receipts:
            assert text
            assert text.count("Asha Test") == 1
            assert text.count("Dr Rao") == 1
            assert "{" not in text and "}" not in text


def test_prewrite_question_builders_fail_closed_on_incomplete_receipts():
    assert (
        build_booking_confirmation_question(
            "en",
            booking_type="unknown",
            patient_name="Asha",
            doctor_name="Dr Rao",
            date_=D,
            time_=T,
        )
        is None
    )
    assert (
        build_booking_confirmation_question(
            "en",
            booking_type="appointment",
            patient_name="Asha",
            doctor_name="Dr Rao",
            date_=D,
        )
        is None
    )
    assert (
        build_cancellation_confirmation_question(
            "en", {"patient_name": "Asha", "doctor": "Dr Rao", "date": D.isoformat()}
        )
        is None
    )


def test_agent_wiring_is_success_gated_and_reversible():
    src = Path("agent/livekit_minimal/agent.py").read_text(encoding="utf-8")
    helper = src.split("def _speak_deterministic_confirm", 1)[1][:2200]
    assert "settings.voice_deterministic_confirm" in helper
    assert "isinstance(sess, AgentSession)" in helper
    assert "sanitize_for_tts" in helper
    assert src.count("raise StopResponse()") >= 3


def test_clinic_question_ack_is_localized_and_never_needs_second_llm():
    for lang in ("te", "en", "hi", "ta", "kn", "mr", "bn", "ml"):
        text = build_clinic_question_ack(lang)
        assert text and "{" not in text and "}" not in text
        read_failure = build_read_failure_text(lang)
        assert read_failure and "{" not in read_failure and "}" not in read_failure
    src = Path("agent/livekit_minimal/agent.py").read_text(encoding="utf-8")
    block = src.split("async def log_clinic_question", 1)[1].split(
        "async def take_message", 1
    )[0]
    assert "build_clinic_question_ack" in block
    assert "raise StopResponse()" in block
    assert block.index("await self._db.commit()") < block.index(
        "build_clinic_question_ack"
    )


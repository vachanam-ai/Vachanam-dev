from datetime import date, timedelta

import pytest

from agent.services.caller_datetime import (
    clock_time_mentions,
    explicit_booking_date,
    explicit_clock_times,
)


TODAY = date(2026, 8, 21)  # Friday


@pytest.mark.parametrize(
    ("utterance", "language", "expected"),
    [
        ("Book it at 5 AM", "en", ("05:00",)),
        ("Book it at 5 p.m.", "en", ("17:00",)),
        ("five PM", "en", ("17:00",)),
        ("17:00", "en", ("17:00",)),
        ("Book at १२:३० PM", "hi", ("12:30",)),
        ("Book at ۵:۳۰ PM", "en", ("17:30",)),
        ("Book me at 5", "en", ("05:00", "17:00")),
        ("5:15", "en", ("05:15", "17:15")),
        ("at 12", "en", ("12:00",)),
        ("at 0", "en", ("00:00",)),
        ("morning five", "en", ("05:00",)),
        ("five in the evening", "en", ("17:00",)),
        ("half past five", "en", ("05:30", "17:30")),
        ("quarter past five", "en", ("05:15", "17:15")),
        ("quarter after five", "en", ("05:15", "17:15")),
        ("quarter to six", "en", ("05:45", "17:45")),
        ("at noon", "en", ("12:00",)),
        ("at midnight", "en", ("00:00",)),
        ("at fourteen hundred hours", "en", ("14:00",)),
        ("token 5, but book the appointment at 6 PM", "en", ("18:00",)),
        ("My phone number is 9988776655; book at 5 PM", "en", ("17:00",)),
    ],
)
def test_english_and_numeric_clock_receipts(utterance, language, expected):
    assert explicit_clock_times(utterance, language) == expected


def test_clock_time_mentions_keeps_each_claim_separate_for_grounding():
    assert clock_time_mentions(
        "2:30 PM is available. Five P.M. is also available.", "en"
    ) == (("14:30",), ("17:00",))


def test_native_spoken_date_number_does_not_become_a_clock():
    speech = (
        "డాక్టర్ Dr Rao గారు ఆగస్టు ఇరవై ఎనిమిది "
        "సాయంత్రం ఐదు గంటలకి అందుబాటులో ఉన్నారు."
    )

    assert clock_time_mentions(speech, "te") == (("17:00",),)


@pytest.mark.parametrize(
    ("utterance", "language", "expected"),
    [
        ("ఉదయం ఐదు గంటలకు", "te", ("05:00",)),
        ("సాయంత్రం ఐదు గంటలకు", "te", ("17:00",)),
        ("सुबह पाँच बजे", "hi", ("05:00",)),
        ("शाम पाँच बजे", "hi", ("17:00",)),
        ("காலை ஐந்து மணிக்கு", "ta", ("05:00",)),
        ("மாலை ஐந்து மணிக்கு", "ta", ("17:00",)),
        ("ಬೆಳಗ್ಗೆ ಐದು ಗಂಟೆಗೆ", "kn", ("05:00",)),
        ("ಸಂಜೆ ಐದು ಗಂಟೆಗೆ", "kn", ("17:00",)),
        ("രാവിലെ അഞ്ച് മണിക്ക്", "ml", ("05:00",)),
        ("വൈകുന്നേരം അഞ്ച് മണിക്ക്", "ml", ("17:00",)),
        ("सकाळी पाच वाजता", "mr", ("05:00",)),
        ("संध्याकाळी पाच वाजता", "mr", ("17:00",)),
        ("সকালে পাঁচটায়", "bn", ("05:00",)),
        ("বিকেলে পাঁচটায়", "bn", ("17:00",)),
    ],
)
def test_native_dayparts_make_one_clock_choice(utterance, language, expected):
    assert explicit_clock_times(utterance, language) == expected


@pytest.mark.parametrize(
    ("utterance", "language"),
    [
        ("five thirty", "en"),
        ("ఐదు ముప్పై", "te"),
        ("पाँच तीस", "hi"),
        ("ஐந்து முப்பது", "ta"),
        ("ಐದು ಮೂವತ್ತು", "kn"),
        ("അഞ്ച് മുപ്പത്", "ml"),
        ("पाच तीस", "mr"),
        ("পাঁচ ত্রিশ", "bn"),
    ],
)
def test_exact_minute_words_stay_ambiguous_without_a_daypart(utterance, language):
    assert explicit_clock_times(utterance, language) == ("05:30", "17:30")


@pytest.mark.parametrize(
    ("utterance", "language", "expected"),
    [
        ("ఐదున్నర", "te", ("05:30", "17:30")),
        ("పావుతక్కువ ఆరు", "te", ("05:45", "17:45")),
        ("साढ़े पाँच", "hi", ("05:30", "17:30")),
        ("सवा पाँच", "hi", ("05:15", "17:15")),
        ("पौने छह", "hi", ("05:45", "17:45")),
        ("ஐந்தரை", "ta", ("05:30", "17:30")),
        ("ஐந்தேகால்", "ta", ("05:15", "17:15")),
        ("ஐந்தேமுக்கால்", "ta", ("05:45", "17:45")),
        ("ಐದುವರೆ", "kn", ("05:30", "17:30")),
        ("ಐದುಕಾಲು", "kn", ("05:15", "17:15")),
        ("ಕಾಲು ಕಡಿಮೆ ಆರು", "kn", ("05:45", "17:45")),
        ("അഞ്ചര", "ml", ("05:30", "17:30")),
        ("അഞ്ചേകാൽ", "ml", ("05:15", "17:15")),
        ("അഞ്ചേമുക്കാൽ", "ml", ("05:45", "17:45")),
        ("साडेपाच", "mr", ("05:30", "17:30")),
        ("सव्वापाच", "mr", ("05:15", "17:15")),
        ("पावणेसहा", "mr", ("05:45", "17:45")),
        ("সাড়ে পাঁচটা", "bn", ("05:30", "17:30")),
        ("সোয়া পাঁচটা", "bn", ("05:15", "17:15")),
        ("পৌনে ছয়টা", "bn", ("05:45", "17:45")),
    ],
)
def test_native_fraction_clock_forms(utterance, language, expected):
    assert explicit_clock_times(utterance, language) == expected


@pytest.mark.parametrize(
    "utterance",
    [
        "age 5:15",
        "aged five thirty years",
        "token 5",
        "phone number 5:15",
        "Appointment on 21.08.2026",
        "5 PM or 6 PM",
        "at 5 or later",
        "from 4:45 to 5:15",
        "between five and six",
        "5 PM, sorry 6 PM",
        "morning or evening at five",
        "I am five years old",
        "24:00",
        "5:60",
    ],
)
def test_clock_parser_fails_closed_on_nonclock_alternative_or_conflict(utterance):
    assert explicit_clock_times(utterance, "en") == ()


@pytest.mark.parametrize(
    ("utterance", "language", "offset"),
    [
        ("today", "en", 0),
        ("tomorrow", "en", 1),
        ("day after tomorrow", "en", 2),
        ("ఈరోజు", "te", 0),
        ("రేపు", "te", 1),
        ("ఎల్లుండి", "te", 2),
        ("आज", "hi", 0),
        ("कल", "hi", 1),
        ("परसों", "hi", 2),
        ("இன்று", "ta", 0),
        ("நாளை", "ta", 1),
        ("நாளை மறுநாள்", "ta", 2),
        ("ಇಂದು", "kn", 0),
        ("ನಾಳೆ", "kn", 1),
        ("ನಾಡಿದ್ದು", "kn", 2),
        ("ഇന്ന്", "ml", 0),
        ("നാളെ", "ml", 1),
        ("മറ്റന്നാൾ", "ml", 2),
        ("आज", "mr", 0),
        ("उद्या", "mr", 1),
        ("परवा", "mr", 2),
        ("আজ", "bn", 0),
        ("আগামীকাল", "bn", 1),
        ("পরশু", "bn", 2),
    ],
)
def test_relative_dates_in_all_languages(utterance, language, offset):
    assert explicit_booking_date(utterance, TODAY, language) == (TODAY + timedelta(days=offset)).isoformat()


@pytest.mark.parametrize(
    ("utterance", "language", "expected"),
    [
        ("Monday", "en", "2026-08-24"),
        ("సోమవారం", "te", "2026-08-24"),
        ("मंगलवार", "hi", "2026-08-25"),
        ("புதன்கிழமை", "ta", "2026-08-26"),
        ("ಗುರುವಾರ", "kn", "2026-08-27"),
        ("വെള്ളിയാഴ്ച", "ml", "2026-08-21"),
        ("शनिवार", "mr", "2026-08-22"),
        ("রবিবার", "bn", "2026-08-23"),
        ("next Friday", "en", "2026-08-28"),
        ("tomorrow Saturday", "en", "2026-08-22"),
    ],
)
def test_weekday_dates_in_all_languages(utterance, language, expected):
    assert explicit_booking_date(utterance, TODAY, language) == expected


@pytest.mark.parametrize(
    ("utterance", "expected"),
    [
        ("2026-08-31", "2026-08-31"),
        ("31/08/2026", "2026-08-31"),
        ("31-08-2026", "2026-08-31"),
        ("31.08.2026", "2026-08-31"),
        ("Aug 22 2026", "2026-08-22"),
        ("August 22, 2026", "2026-08-22"),
        ("22 August 2026", "2026-08-22"),
        ("22nd Aug. 2026", "2026-08-22"),
    ],
)
def test_explicit_calendar_dates(utterance, expected):
    assert explicit_booking_date(utterance, TODAY, "en") == expected


@pytest.mark.parametrize(
    "utterance",
    [
        "08/09/2026",
        "31/02/2026",
        "2026-02-31",
        "February 31, 2026",
        "today or tomorrow",
        "Monday to Friday",
        "tomorrow Monday",
        "2026-08-22 2026-08-23",
        "21/08/26",
    ],
)
def test_date_parser_rejects_ambiguous_invalid_alternative_or_conflicting_dates(utterance):
    assert explicit_booking_date(utterance, TODAY, "en") is None

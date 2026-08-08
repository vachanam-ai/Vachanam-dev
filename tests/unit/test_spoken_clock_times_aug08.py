"""A clock time never reaches TTS with a colon in it.

Vinay 2026-08-08: "time is getting read as 6 colon zero zero instead of 6pm
sometimes."

"Sometimes" is the whole diagnosis. The model writes "సాయంత్రం ఆరు" on most
turns and a numeric "6:00" on the rest, and only the numeric ones broke.

The three passes that handle this have existed since #415/#421 — but only
inside `spoken_english_numbers`, which stopped being the production TTS
boundary when `sanitize_for_tts` moved to `spoken_phone_digits`. That one
leaves times alone on the theory that "Soniox can render them naturally in the
call language". It cannot: a bare "6:00" comes out as its literal characters.
RULE 6 — a colon is a symbol, and symbols sound broken on a phone.

English time words inside a Telugu sentence are deliberate, not a slip: #415 is
Vinay asking for exactly that, validated on real calls.
"""
import pytest

from agent.services.tts_sanitizer import sanitize_for_tts, spoken_clock_times


@pytest.mark.parametrize("text", [
    "Your appointment is at 6:00 PM.",
    "మీ అపాయింట్‌మెంట్ సాయంత్రం 6:00 గంటలకు.",
    "appointment 18:00 ki fix chesanu",
    "Doctor is free at 9:30 and 11:00.",
    "రేపు 11:00 గంటలకు",
    "moved to 11:00 a.m. tomorrow",
    "5:30pm",
    "देखिए 10:00 बजे",
])
def test_no_colon_survives_to_tts(text):
    """The reported symptom, in every language the clinic runs."""
    assert ":" not in sanitize_for_tts(text)


# ── the reported case, exactly ───────────────────────────────────────────────

def test_six_pm_is_spoken_as_six_pm():
    assert sanitize_for_tts("Your appointment is at 6:00 PM.") == (
        "Your appointment is at six P.M."
    )


def test_a_24_hour_clock_becomes_a_12_hour_one():
    assert "six P.M." in sanitize_for_tts("appointment 18:00 ki fix chesanu")


def test_a_written_meridiem_is_not_left_bare():
    """#415: TTS says a lowercase "am" as the word "amm". The dotted form is
    the letter-by-letter rendering every engine agrees on."""
    out = sanitize_for_tts("call at 10:00 am")
    assert "A.M." in out
    assert not out.endswith(" am")


def test_a_written_meridiem_beats_a_guessed_one():
    """"ఉదయం 10:00 pm" is a contradiction; the one they WROTE wins."""
    assert "P.M." in sanitize_for_tts("ఉదయం 10:00 pm")


def test_half_past_survives_as_words():
    assert "nine thirty" in sanitize_for_tts("free at 9:30")


def test_the_meridiem_dot_does_not_double_the_full_stop():
    """The o'clock-word pass eats "గంటలకు" and can strand the sentence stop
    against the meridiem's own dot — "six P.M..", which TTS pauses on."""
    assert ".." not in sanitize_for_tts("మీ అపాయింట్‌మెంట్ సాయంత్రం 6:00 గంటలకు.")


# ── things that must NOT be treated as times ─────────────────────────────────

def test_the_word_am_is_not_a_meridiem():
    assert sanitize_for_tts("I am fine") == "I am fine"


def test_a_phone_number_is_still_read_digit_by_digit():
    out = sanitize_for_tts("Call 9876543210 at 10:00 am.")
    assert "nine eight seven six five four three two one zero" in out
    assert "A.M." in out


def test_a_token_number_is_left_alone():
    """Tokens, ages and fees are not times — only colon-times are touched."""
    assert "Token 12" in sanitize_for_tts("Token 12. Come at 11:00.")


def test_text_with_no_time_is_untouched():
    assert spoken_clock_times("no times here at all") == "no times here at all"


def test_empty_input_is_safe():
    assert spoken_clock_times("") == ""
    assert spoken_clock_times(None) == ""


# ── the wiring itself ────────────────────────────────────────────────────────

def test_the_production_boundary_actually_calls_it():
    """The passes existed for weeks and did nothing because nothing on the live
    path called them. That is the bug, so assert the CALL, not the helper."""
    import inspect

    assert "spoken_clock_times" in inspect.getsource(sanitize_for_tts)

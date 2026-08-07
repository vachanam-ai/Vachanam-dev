"""Asking to book is a request, not a formality — and the rule is never spoken.

Real call 2026-08-03, 7:44pm (Vinay): the agent said "you haven't explicitly told
to book appointment, without that i can't book". Two faults in one sentence.

  1. It refused instead of asking. A caller who names a doctor, a day or a time
     IS asking to book. The agent should check the slot and put ONE confirmation
     question — "he is available then, shall I book?" — and on a yes, book
     immediately, with no repetition.
  2. It read an internal rule out loud. <private_channel> already forbids
     narrating tool mechanics; a permission rule is the same class of thing. No
     receptionist tells a patient "you did not phrase that as an instruction".

Same call booked "10 AM" while it was 7:44pm, with no date spoken, so it read as
today. A time without a date is the ambiguity — the confirmation must name the
date, and a time already past today must never be booked for today.
"""
import pytest

from agent.prompts.grounded_prompt import build_grounded_prompt
from agent.prompts.system_prompt import DoctorContext


def _prompt(language: str = "en") -> str:
    """Whitespace-normalized: the prompt hard-wraps, so a rule can be split
    across lines. Pinning the wrapping would make every reflow a test failure —
    what matters is that the sentence is present."""
    return " ".join(_raw(language).split())


def _raw(language: str = "en") -> str:
    return build_grounded_prompt(
        clinic_name="Test Clinic",
        doctors=[
            DoctorContext(
                id="d1", name="Dr Lakshmi", specialization="Skin",
                routing_keywords=["skin"], booking_type="appointment",
                is_default=False,
                schedule={"0": [{"start": "09:00", "end": "13:00"}]},
            )
        ],
        emergency_contact="+919000000000",
        plan="clinic",
        language=language,
    )


def test_naming_a_time_is_treated_as_a_booking_request():
    text = _prompt()
    assert "IS asking to book" in text
    assert "Do not wait to be asked in exact words" in text


def test_exactly_one_confirmation_question_then_book():
    text = _prompt()
    # Vinay 2026-08-07 gave the exact shape he wants, and it names the patient:
    # "okay vinay, shall i confirm your appointment at 9am with dr.srinivas?"
    # Same single question as the 08-03 rule this test was written for — the
    # name and the date were added, the "ask it once" contract is unchanged.
    assert "shall I confirm your appointment" in text
    assert "Okay <name>" in text
    assert "confirm_booking IMMEDIATELY" in text
    assert "Ask that question ONCE" in text
    assert "never re-confirm a booking already made" in text


def test_the_permission_rule_is_never_spoken_to_the_caller():
    """The exact sentence a patient heard. It must be impossible to justify."""
    text = _prompt()
    assert "NEVER tell a caller you lack permission" in text
    assert "clinic rules are never spoken aloud" in text
    # The old wording invited a refusal rather than a question.
    assert "Call it only after explicit caller permission" not in text


def test_a_time_is_always_offered_with_its_date():
    text = _prompt()
    assert "ALWAYS name the DATE" in text
    assert "leaves the caller assuming today" in text


def test_a_time_already_past_today_is_never_booked_for_today():
    text = _prompt()
    assert "never book it for today" in text
    assert "offer the next day the doctor sits at that time" in text


def test_when_is_he_free_reads_free_time_not_the_sitting_block():
    """8pm, 8:15 taken: the answer is "8 to 8:15 and 8:30 to 9", not the sitting
    block — booked slots and passed time are not availability."""
    text = _prompt()
    assert "free_now, NOT sitting_hours" in text
    assert "Read ALL the free ranges in ONE answer" in text


@pytest.mark.parametrize("language", ["te", "hi", "en"])
def test_the_rule_survives_every_language_render(language):
    """The prompt is rebuilt per active language; a rule that only exists in the
    English render protects nobody — this clinic runs in Telugu."""
    text = _prompt(language)
    assert "shall I confirm your appointment" in text
    assert "NEVER tell a caller you lack permission" in text

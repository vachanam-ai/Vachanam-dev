"""#365 (Vinay real call 2026-07-14): "book for my father tomorrow" booked to
the CALLER's number with no ask. For different-person bookings the agent must
ask ONE whose-number question before the final readback; self-bookings never
get that question.
"""
from agent.prompts.system_prompt import build_system_prompt


def _prompt():
    return build_system_prompt(
        clinic_name="C", doctors=[], emergency_contact="+911234567890",
        plan="clinic", language="te", faq=None,
    )


def test_whose_number_question_exists_for_family_bookings():
    p = _prompt()
    assert "WHOSE NUMBER" in p
    assert "only when the booking is for someone else" in p


def test_self_bookings_never_get_the_question():
    p = _prompt()
    assert "Self-bookings NEVER get this question" in p


def test_one_confirmation_rule_carves_out_the_exception():
    p = _prompt()
    assert "WHOSE NUMBER question of step 5" in p
    # the single-confirmation principle itself must survive
    assert "EXACTLY ONE yes-question" in p


def test_dictated_number_still_hard_gated():
    # a different number given for the patient must go through the digit
    # read-back gate — the whose-number rule defers to PHONE NUMBER RULES
    p = _prompt()
    assert "PHONE NUMBER RULES" in p
    assert "NEVER call confirm_booking with a dictated number" in p

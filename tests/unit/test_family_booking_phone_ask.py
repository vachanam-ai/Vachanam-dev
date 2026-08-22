"""Family bookings always share the verified incoming caller number."""
from agent.prompts.system_prompt import build_system_prompt


def _prompt():
    return build_system_prompt(
        clinic_name="C", doctors=[], emergency_contact="+911234567890",
        plan="clinic", language="te", faq=None,
    )


def test_family_booking_never_asks_for_another_number():
    p = _prompt()
    assert "ALWAYS the verified incoming" in p
    assert "Never ask for, accept, read back, or pass another number" in p


def test_no_whose_number_question_remains():
    p = _prompt()
    assert 'Ask "this number or theirs"' not in p


def test_one_confirmation_rule_survives():
    p = _prompt()
    assert "exactly one natural yes-question" in p.lower()


def test_multiple_family_members_explicitly_allowed():
    p = _prompt()
    assert "Multiple family members may book separate same-day appointments" in p

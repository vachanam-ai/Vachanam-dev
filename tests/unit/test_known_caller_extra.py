from agent.livekit_minimal.agent import KNOWN_CALLER_BOOKING_EXTRA


def test_extra_drives_self_vs_other():
    text = KNOWN_CALLER_BOOKING_EXTRA.format(name="Ravi")
    assert "Ravi" in text
    low = text.lower()
    # Must instruct the self/other question and the two branches.
    assert "someone else" in low or "for you" in low
    assert "different_person=true" in low          # family member branch
    assert "different_person=false" in low         # self branch
    # Self branch: no name/age re-asked.
    assert "age" in low


def test_extra_relation_word_skips_the_question():
    """Vinay 2026-07-03 case 1: 'appointment for my father' must be understood
    directly — the agent must NOT re-ask 'for you or someone else?'."""
    low = KNOWN_CALLER_BOOKING_EXTRA.format(name="Ravi").lower()
    assert "relation word" in low
    assert "for my father" in low
    assert "do not ask" in low.replace("n't", "not") or "not ask" in low


def test_extra_forces_verified_caller_number_for_family():
    low = KNOWN_CALLER_BOOKING_EXTRA.format(name="Ravi").lower()
    assert "always uses the verified number this call came from" in low
    assert "never ask for, accept, repeat, or pass another phone number" in low
    assert "same caller number on the same day" in low

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


def test_extra_asks_this_number_or_new_number():
    """Vinay 2026-07-03 case 1: for a family booking, ask ONE question — book on
    the calling number or the person's own number; a given number follows the
    10-digit read-back rules and is passed as patient_phone."""
    low = KNOWN_CALLER_BOOKING_EXTRA.format(name="Ravi").lower()
    assert "own number" in low
    assert "patient_phone" in low
    assert "phone number rules" in low
    assert "10" in low  # exactly 10 digits rule referenced

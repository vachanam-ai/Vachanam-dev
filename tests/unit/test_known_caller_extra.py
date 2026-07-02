from agent.livekit_minimal.agent import KNOWN_CALLER_BOOKING_EXTRA


def test_extra_drives_self_vs_other():
    text = KNOWN_CALLER_BOOKING_EXTRA.format(name="Ravi")
    assert "Ravi" in text
    low = text.lower()
    # Must instruct the self/other question and the two branches.
    assert "someone else" in low or "for you" in low
    assert "different_person=true" in low          # family member branch
    assert "different_person=false" in low         # self branch
    # Self branch: no name/age re-asked; phone optional for the other person.
    assert "optional" in low
    assert "age" in low

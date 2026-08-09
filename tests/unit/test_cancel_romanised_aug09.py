"""The agent must not teach a caller a word it then refuses to understand.

Vinay 2026-08-09, live call: "speaking raddu instead of cancel. unable to
cancel bookings. saying sanketika samasya instead of technical issue."

A loop this codebase built for itself:

    agent says  "రద్దు"                        (literary Telugu)
    caller says "raddu cheyandi"               (mirrors it back)
    Soniox returns it in LATIN letters
    _caller_authorized_cancellation matched NOTHING  -> cancel impossible

_CANCEL_AUTH_TERMS held native script only. So the one word the agent had just
taught the caller was the one word that could never authorise a cancellation.

This is #502 in the sibling I consciously left alone two days earlier:
reschedule's phrase list was removed precisely because Latin-script Telugu
matched none of it, and I wrote down "cancel is destructive, keeps its gate"
without checking that its gate had the identical hole. Third instance of one
defect in a week.

Widening REQUEST recognition does not weaken safety: the destructive step is
still gated on a positive `_caller_affirmed`. Failing to recognise the ask
never protected anyone — it trapped them.
"""
import pytest

from agent.livekit_minimal.agent import (
    _caller_authorized_cancellation as authorised,
)
from agent.services.tts_sanitizer import sanitize_for_tts


# ── the reported failure ─────────────────────────────────────────────────────

@pytest.mark.parametrize("said", [
    "raddu cheyandi",
    "raddu chey",
    "naa appointment raddu cheyandi",
    "radhu cheyandi",
    "appointment raddu",
    "booking raddu cheyandi",
    "kyansil cheyandi",
    "ratthu pannunga",
])
def test_romanised_cancellation_is_recognised(said):
    assert authorised(said), f"cancel impossible for a caller saying {said!r}"


@pytest.mark.parametrize("said", ["cancel cheyandi", "cancel it", "రద్దు చేయండి",
                                  "క్యాన్సిల్ చేయండి"])
def test_the_forms_that_already_worked_still_work(said):
    assert authorised(said)


# ── and the negatives, which is where widening gets dangerous ────────────────

@pytest.mark.parametrize("said", [
    "raddu cheyoddu",       # romanised "don't cancel" — the veto only knew
    "raddu cheyavaddu",     # native script and English before this
    "రద్దు చేయొద్దు",
    "dont cancel",
    "do not cancel it",
    "did you already cancel",
])
def test_a_refusal_to_cancel_is_never_read_as_a_request(said):
    assert not authorised(said), f"would have cancelled on {said!r}"


@pytest.mark.parametrize("said", ["my name is Radhu", "Radhu speaking",
                                  "I am Raddu"])
def test_a_caller_named_radhu_does_not_trigger_a_cancellation(said):
    """Raddu/Radhu is a real name. A bare word match read an introduction as a
    cancellation request — caught by this file's own negatives before it
    shipped, which is why the romanised form must carry an action or object."""
    assert not authorised(said)


@pytest.mark.parametrize("said", ["I want to book", "reschedule cheyandi",
                                  "what time is the doctor free"])
def test_other_intents_are_not_cancellations(said):
    assert not authorised(said)


# ── stop teaching the caller the wrong word in the first place ───────────────

def test_the_agent_says_cancel_not_raddu():
    """The grounded prompt has asked for this since it was written — there is a
    correction example for exactly this sentence — and the model still emitted
    the formal form. A prompt is a request; the chokepoint is the guarantee."""
    out = sanitize_for_tts("మీ అపాయింట్‌మెంట్ రద్దు చేయబడింది.")
    assert "రద్దు" not in out
    assert "క్యాన్సిల్" in out


def test_technical_issue_is_not_newsreader_telugu():
    out = sanitize_for_tts("సాంకేతిక సమస్య వచ్చింది అండి.")
    assert "సాంకేతిక" not in out
    assert "టెక్నికల్" in out


def test_english_is_left_alone():
    text = "Your appointment is cancelled."
    assert sanitize_for_tts(text) == text


def test_the_swap_runs_on_the_production_boundary():
    """The clock-time passes existed for weeks doing nothing because nothing on
    the live path called them. Assert the CALL, not the helper."""
    import inspect

    assert "spoken_clinic_words" in inspect.getsource(sanitize_for_tts)


def test_the_swap_and_the_guard_agree():
    """The whole point: whatever the agent now SAYS must be a word the
    cancellation guard can UNDERSTAND when the caller repeats it."""
    spoken = sanitize_for_tts("రద్దు చేయనా?")
    assert "క్యాన్సిల్" in spoken
    assert authorised("క్యాన్సిల్ చేయండి")
    assert authorised("kyansil cheyandi")

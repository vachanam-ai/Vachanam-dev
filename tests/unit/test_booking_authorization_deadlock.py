"""A caller who agrees must be able to get booked.

Real call 2026-08-03 (Vinay): "it pushbacked multiple times for booking
appointment. until i explicitly said book appointment. which is very annoying."
The captured agent log shows it exactly:

    executing tool: Booking blocked: the caller did not ask to book
                    or confirm...                                   x12
    "function": "confirm_booking"                                   x4

The model tried to book four times; the guard rejected twelve. Three locks, all
needed at once:

  1. _caller_authorized_booking wants the literal word "book" or a phrase from a
     fixed list.
  2. The only other route needs the ASSISTANT to have asked a booking
     confirmation question — but the guard's message told it to "wait for an
     explicit booking request", so it refused aloud instead of asking. No
     question, so route 2 could never open. Guard blocks -> no question -> no
     valid yes -> guard blocks. A deadlock only the magic words could break.
  3. _caller_affirmed was exact set-membership, so "yes book it" and a bare
     Telugu "సరే" were not agreement at all.

The guard itself is right and stays: a bare availability question must never
mutate anything. What changes is that agreeing now works.
"""
import pytest

from agent.livekit_minimal.agent import _caller_affirmed, _caller_authorized_booking


# ── the caller agrees, in the ways people really agree ──────────────────────

@pytest.mark.parametrize("said", [
    "yes",
    "yes please",
    "yes book it",
    "ok do it",
    "okay, go ahead",
    "sure",
    "అవును",
    "సరే",            # bare Telugu "ok" — was NOT recognised
    "అలాగే",          # bare Telugu "alright" — was NOT recognised
    "సరే బుక్ చేయండి",  # agreement plus the instruction
    "हाँ",
    "ठीक है",
])
def test_agreement_is_recognised(said):
    assert _caller_affirmed(said) is True, f"{said!r} is a yes"


# ── refusal must still fail closed ─────────────────────────────────────────

@pytest.mark.parametrize("said", [
    "no",
    "no don't book",
    "not now",
    "no, cancel that",
    "వద్దు",
    "లేదు",
    "नहीं",
    "இல்லை",
    "",
])
def test_refusal_never_authorizes_a_write(said):
    assert _caller_affirmed(said) is False, f"{said!r} must not authorize"


def test_a_negation_anywhere_beats_a_leading_yes():
    """"yes but don't book yet" opens with a yes and must still fail closed —
    a write is not reversible from the caller's side."""
    assert _caller_affirmed("yes but do not book yet") is False


# ── the guard still does its job ───────────────────────────────────────────

def test_an_availability_question_is_not_authorization():
    """RULE the guard exists for: reading is not writing."""
    assert _caller_authorized_booking("is the doctor free at 8") is False
    assert _caller_authorized_booking("confirm if the doctor is available") is False
    assert _caller_authorized_booking("did you already book it?") is False


def test_an_explicit_request_still_authorizes():
    assert _caller_authorized_booking("book it") is True
    assert _caller_authorized_booking("బుక్ చేయండి") is True


def test_a_negative_instruction_never_authorizes():
    assert _caller_authorized_booking("do not book it") is False
    assert _caller_authorized_booking("I don't want to book") is False


# ── the blocked path must ASK, never lecture ───────────────────────────────

def test_the_server_builds_and_verifies_the_booking_question():
    """The question is deterministic and arms consent only after playout."""
    import inspect

    from agent.livekit_minimal.agent import VachanamAgent

    src = inspect.getsource(VachanamAgent.confirm_booking)
    assert "build_booking_confirmation_question" in src
    assert "wait_for_playout" in src
    assert "booking_confirmation_snapshot = snapshot" in src
    assert 'pending_confirmation = "book"' in src
    assert "booking_confirmation_playout_interrupted" in src
    assert "Wait for an explicit booking request" not in src


def test_cancel_and_reschedule_carry_the_same_fix():
    """Vinay's same call: "i told to cancel tomorrow morning appointment... it
    said appointment canceled and ended the call. in reality nothing changed."
    Cancel and reschedule had the identical refuse-instead-of-ask wording, so
    they deadlocked the same way.

    RESCHEDULE HAS SINCE LEFT THIS GROUP (2026-08-08). Asking at all is what
    kept looping — the question was asked in seven languages and the answer
    matched against a phrase list that had no Latin-script Telugu in it — so
    Vinay's instruction was to stop asking: "please reschedule to 11am tomorrow
    -> done". A mutation that never demands a question cannot deadlock on one.
    Cancel keeps the ask because it is destructive."""
    import inspect

    from agent.livekit_minimal.agent import VachanamAgent

    cancel = inspect.getsource(VachanamAgent.cancel_booking)
    reschedule = inspect.getsource(VachanamAgent.reschedule_booking)
    assert "build_cancellation_confirmation_question" in cancel
    assert "wait_for_playout" in cancel
    assert "cancellation_confirmation_snapshot" in cancel
    assert 'pending_confirmation = "cancel"' in cancel
    assert "build_cancellation_confirmation_question" not in reschedule
    assert "NO CONFIRMATION QUESTION AT ALL" in reschedule

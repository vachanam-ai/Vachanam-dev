"""Reschedule and cancel ask to confirm once, like booking does.

Vinay 2026-08-07: "reschedule call asking 2 times to confirm."

#495 gave confirm_booking sticky consent and left these two on the old
phrase-matching path, so they kept the exact shape of the bug:

    you   : move my appointment to 11
    agent : shall I move it to 11?          <- not one of the five phrases
                                               _last_assistant_requested_
                                               reschedule matches
    you   : yes                             -> REFUSED. the guard NOW arms
                                               pending_confirmation and orders
                                               a re-ask
    agent : shall I reschedule it?          <- second question
    you   : yes                             -> works

Exactly two, every time. Fixing one mutation and not its two identical
siblings is what produced this.

CANCEL KEEPS ITS ASYMMETRY. Cancelling is destructive, so "not a refusal" is
still not enough there — the caller must actually affirm. What changed is that
the affirmation no longer has to land on the same turn as the word "cancel",
and the question no longer has to match a hardcoded phrase.
"""
import inspect

import pytest

from agent.livekit_minimal.agent import (
    VachanamAgent,
    _caller_authorized_reschedule,
)
from agent.session_state import SessionState


# ── asking to move it, in the words people use ───────────────────────────────

@pytest.mark.parametrize("said", [
    # The one that failed. The list had "move THE appointment" and this is how
    # everybody actually says it, so consent was never recorded at all and the
    # sticky flag above could not help.
    "move my appointment to 11",
    "change my appointment to 11",
    "shift my booking to friday",
    "push my appointment to evening",
    "postpone it to monday",
    "reschedule my appointment",
    # Already worked; must keep working.
    "move the appointment", "change it to 11", "shift it",
])
def test_a_request_to_move_is_recognised(said):
    assert _caller_authorized_reschedule(said) is True


@pytest.mark.parametrize("said", [
    "what time is my appointment",   # read-only
    "what is my token number",
    "dont reschedule it",            # explicit negative
    "i want to book an appointment", # a different mutation entirely
    "cancel my appointment",         # ditto
    "can you change my doctor",      # not a time change
])
def test_it_does_not_over_match(said):
    assert _caller_authorized_reschedule(said) is False


def _src(name):
    return inspect.getsource(getattr(VachanamAgent, name))


# ── the state ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("field", [
    "caller_asked_to_book", "caller_asked_to_reschedule", "caller_asked_to_cancel",
])
def test_every_mutation_remembers_consent_and_starts_unset(field):
    assert getattr(SessionState(), field) is False


@pytest.mark.parametrize("field,fn", [
    ("caller_asked_to_reschedule", "_caller_authorized_reschedule"),
    ("caller_asked_to_cancel", "_caller_authorized_cancellation"),
])
def test_the_turn_handler_records_each_request(field, fn):
    src = _src("on_user_turn_completed")
    assert f"{field} = True" in src
    assert fn in src


def test_a_flat_refusal_withdraws_all_three():
    """One "no" ends the whole negotiation, not just the booking half."""
    src = _src("on_user_turn_completed")
    block = src.split(
        "declined_turn = _caller_refused_outright(utterance)", 1
    )[1].split("else:", 1)[0]
    for field in (
        "caller_asked_to_book", "caller_asked_to_reschedule", "caller_asked_to_cancel"
    ):
        assert f"{field} = False" in block


def test_recording_consent_is_not_mutually_exclusive():
    """A caller can say "cancel the 10am and book me at 11" in one breath. An
    if/elif chain would record only the first and re-block the other."""
    src = _src("on_user_turn_completed")
    after = src.split(
        "declined_turn = _caller_refused_outright(utterance)", 1
    )[1]
    body = after.split("else:")[1] if "else:" in after else after
    assert body.count("if _caller_authorized") == 3, (
        "the three intents are recorded as an elif chain; a single utterance "
        "asking for two of them will only register one"
    )


# ── the guards ───────────────────────────────────────────────────────────────

def test_reschedule_accepts_remembered_consent():
    src = _src("reschedule_booking")
    assert "self._state.caller_asked_to_reschedule" in src, (
        "reschedule still needs the yes on the same turn as the request, or a "
        "hardcoded phrase match — it will keep asking twice"
    )


def test_cancel_accepts_remembered_consent():
    src = _src("cancel_booking")
    assert "self._state.caller_asked_to_cancel" in src


def test_cancel_still_requires_a_positive_yes():
    """The deliberate asymmetry. Booking on a shrug is recoverable; silently
    cancelling a real appointment is not."""
    cancel = _src("cancel_booking")
    turn = _src("on_user_turn_completed")
    assert "cancellation_confirmation_granted" in cancel
    assert "cancellation_confirmation_snapshot" in cancel
    assert "_caller_affirmed(utterance)" in turn


def test_reschedule_does_not_require_a_positive_yes():
    """Moving an appointment the caller asked to move needs no second yes —
    that is the whole complaint."""
    src = _src("reschedule_booking")
    assert "_caller_affirmed" not in src


# reschedule_booking dropped out on 2026-08-08: it no longer consults
# remembered consent at all, so there is no ordering left to get wrong. Its
# replacement rule — a flat no is the ONLY thing that stops a move — is in
# test_reschedule_no_confirm_aug08.
@pytest.mark.parametrize("tool", ["cancel_booking"])
def test_a_refusal_is_checked_before_remembered_consent(tool):
    src = _src(tool)
    assert "_caller_declined" in src
    assert src.index("if declined:") < src.index(
        "if self._state.cancellation_confirmation_granted:"
    )


# ── consent is spent, not permanent ──────────────────────────────────────────

def test_a_completed_reschedule_spends_its_consent():
    """Otherwise one "move it" authorizes every later move in the call."""
    src = _src("_do_reschedule")
    assert "caller_asked_to_reschedule = False" in src


def test_a_completed_cancellation_spends_its_consent():
    src = _src("_do_cancel")
    assert "caller_asked_to_cancel = False" in src


def test_each_mutation_uses_its_deliberate_consent_shape():
    """Booking/cancel use snapshots; reschedule uses its narrow withdrawal veto."""
    booking = _src("confirm_booking")
    reschedule = _src("reschedule_booking")
    cancel = _src("cancel_booking")

    assert "booking_confirmation_granted" in booking
    assert "booking_confirmation_snapshot" in booking
    assert "_caller_withdrew_reschedule" in reschedule
    assert "cancellation_confirmation_granted" in cancel
    assert "cancellation_confirmation_snapshot" in cancel

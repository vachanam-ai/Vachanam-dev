"""The confirmation question is asked once, and once only.

Vinay 2026-08-07, after the third looping call: "we need shall i book once and
only once before booking. that too should looke like natural." His flow:

    what time you want            -> 9am
    whats your name, age          -> vinay, i don't say
    okay vinay, shall i confirm your appointment at 9am with dr.srinivas?
                                  -> yes
    done, we booked.

WHY IT REPEATED. Authorization was re-derived from the LATEST utterance on
every call to confirm_booking. The caller asked to book at turn one, but by
the time they answered "vinay, 28" that utterance held no booking words, so
the guard read them as someone who had never asked, refused the write, and
raised a ToolError instructing the model to ask again. The model asked, the
caller agreed, the next answer again contained no booking words, and round it
went until he hung up. The guard's own rejection was the fuel.

Consent is now remembered for the call (`caller_asked_to_book`). The guard
stops rejecting, so nothing can order a second question. The question is still
asked — the prompt asks for it — but only the prompt asks, and it says once.
"""
import inspect

import pytest

from agent.livekit_minimal.agent import VachanamAgent
from agent.session_state import SessionState


def _src(name):
    return inspect.getsource(getattr(VachanamAgent, name))


# ── consent is remembered, not re-derived ────────────────────────────────────

def test_consent_starts_unset():
    assert SessionState().caller_asked_to_book is False


def test_the_turn_handler_records_a_request_to_book():
    src = _src("on_user_turn_completed")
    assert "caller_asked_to_book = True" in src
    assert "_caller_authorized_booking" in src


def test_a_flat_refusal_withdraws_it():
    src = _src("on_user_turn_completed")
    assert "caller_asked_to_book = False" in src
    assert "_caller_refused_outright" in src


def test_confirm_booking_accepts_remembered_consent():
    """The whole point: answering "vinay, 28" must not un-authorize a booking
    the caller asked for two turns earlier."""
    src = _src("confirm_booking")
    assert "self._state.caller_asked_to_book" in src, (
        "confirm_booking still judges consent only from the latest utterance; "
        "every answer the caller gives will keep re-blocking the booking"
    )


def test_consent_is_spent_by_a_completed_booking():
    """A second booking on the same call — the other family member — is a new
    decision and gets its own question."""
    src = _src("confirm_booking")
    after = src.split("any_booking_confirmed = True")[1]
    assert "caller_asked_to_book = False" in after


def test_consent_is_spent_on_success_not_on_authorization():
    """Cleared at authorization instead, a retry after a transient failure
    would have to ask the caller all over again."""
    src = _src("confirm_booking")
    auth_block = src.split("any_booking_confirmed = True")[0]
    # the disarm that happens at authorization time is pending_confirmation,
    # and it must NOT take the sticky consent with it
    assert "caller_asked_to_book = False" not in auth_block


def test_an_outright_refusal_still_blocks_even_with_remembered_consent():
    """Sticky consent must not outrank a flat no."""
    src = _src("confirm_booking")
    assert "not declined" in src
    idx_declined = src.index("not declined")
    idx_sticky = src.index("caller_asked_to_book")
    assert idx_declined < idx_sticky, (
        "remembered consent is checked before the refusal veto; a caller "
        "saying no would still get booked"
    )


# ── the question itself ──────────────────────────────────────────────────────

def _prompt(lang="en"):
    from agent.prompts.grounded_prompt import build_grounded_prompt

    return build_grounded_prompt(
        clinic_name="Test Clinic", doctors=[], emergency_contact="+919000000000",
        plan="clinic", language=lang,
    )


def test_name_and_age_are_one_question():
    flat = " ".join(_prompt().split())
    assert "Ask name and age in ONE question" in flat


def test_a_declined_age_is_accepted_not_chased():
    """"vinay, i don't say" — take the name, drop the age, move on."""
    flat = " ".join(_prompt().split())
    assert "decline their age, take what they gave and move on" in flat
    assert "Never ask twice for an age" in flat


def test_the_confirmation_question_uses_the_patients_name():
    flat = " ".join(_prompt().split())
    assert "Okay <name> — shall I confirm your appointment" in flat
    assert "<time> on <date> with <doctor>" in flat


def test_the_prompt_still_says_ask_it_only_once():
    flat = " ".join(_prompt().split())
    assert "Ask that question ONCE" in flat
    assert "Never re-ask it" in flat


@pytest.mark.parametrize("lang", ["te", "hi", "ta", "kn", "mr", "en"])
def test_the_rule_reaches_every_language(lang):
    """The loop was worst in Hindi. A rule that only exists in the English
    prompt fixes nothing for the languages that actually broke."""
    flat = " ".join(_prompt(lang).split())
    assert "Ask name and age in ONE question" in flat
    assert "Ask that question ONCE" in flat

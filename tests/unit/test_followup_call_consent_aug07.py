"""A clinic-initiated visit call must not ask the patient to confirm twice.

Vinay 2026-08-07: "test treatment follow up calls. this is where i doubt about
breaking now." He was right to look here.

Sticky consent (#495/#497) fixed the INBOUND shape: the patient says "book me
an appointment", `caller_asked_to_book` records it, and answering a question
two turns later no longer withdraws it.

An outbound follow-up call is the mirror image and the fix could not reach it.
WE ring THEM because their doctor asked them to come back, so the patient
never says "book" at all — the flag can never be set from an utterance, and
the guard fell through to matching the model's own phrasing against a fixed
list. The prompt tells it to "confirm in one breath", which produces lines
like "Thursday 10 AM tho Dr Srinivas dagara — confirm chestara?", matching
none of the listed phrases. So the patient's "sare" was refused, the guard
armed and ordered a re-ask, and they were asked again.

Simulated before the fix existed: the follow-up flow reached "REFUSED, guard
orders a re-ask" on the patient's agreement.

The doctor's instruction plus the patient's agreement IS the consent on this
call. Requiring them to request a booking they were phoned about is the wrong
question. A flat no still clears it, and the prompt still asks first.
"""
import inspect

import pytest

from agent.session_state import SessionState


def _entry_src():
    from agent.livekit_minimal import agent as agent_mod

    return inspect.getsource(agent_mod.entrypoint)


def _block(call_type: str) -> str:
    """The lines between this call_type being set and the next elif."""
    src = _entry_src()
    marker = f'state.call_type = "{call_type}"'
    assert marker in src, f"{call_type} is no longer set in the entrypoint"
    return src.split(marker)[1].split("elif")[0]


# ── the calls whose whole purpose is to book ─────────────────────────────────

@pytest.mark.parametrize("call_type", ["next_visit_book", "cascade_rebook"])
def test_a_clinic_initiated_visit_call_seeds_booking_consent(call_type):
    assert "caller_asked_to_book = True" in _block(call_type), (
        f"{call_type} rings the patient to book a visit, but still requires "
        f"them to ASK to book — their agreement will be refused once and the "
        f"agent will ask a second time"
    )


def test_doctor_advice_seeds_both_mutations():
    """That call MOVES the existing visit rather than adding a second one
    (FIXLOG #490), so it may book or reschedule, and the patient asked for
    neither in words."""
    block = _block("doctor_advice")
    assert "caller_asked_to_book = True" in block
    assert "caller_asked_to_reschedule = True" in block


# ── the calls that must NOT be seeded ────────────────────────────────────────

def test_a_reminder_call_is_not_seeded():
    """A reminder confirms attendance. It may end in a reschedule or a cancel,
    and both must still come from the patient — we did not ring them to change
    anything."""
    block = _block("reminder")
    assert "caller_asked_to_book = True" not in block
    assert "caller_asked_to_reschedule = True" not in block
    assert "caller_asked_to_cancel = True" not in block


def test_a_question_answer_call_is_not_seeded():
    """That call delivers the doctor's answer. It books nothing."""
    block = _block("question_answer")
    assert "caller_asked_to" not in block


def test_no_call_type_ever_seeds_cancellation():
    """Nothing justifies pre-authorizing the destructive one. A cancellation
    must always be asked for."""
    src = _entry_src()
    assert "caller_asked_to_cancel = True" not in src


# ── the seed is a starting value, not a permanent grant ──────────────────────

def test_a_refusal_on_a_seeded_call_still_withdraws_consent():
    """"No, I'll call the clinic myself" has to end it, seeded or not."""
    from agent.livekit_minimal.agent import VachanamAgent

    src = inspect.getsource(VachanamAgent.on_user_turn_completed)
    block = src.split("_caller_refused_outright(utterance)")[1].split("else:")[0]
    assert "caller_asked_to_book = False" in block
    assert "caller_asked_to_reschedule = False" in block


def test_a_completed_booking_still_spends_the_seeded_consent():
    """Otherwise one seeded follow-up call could book twice."""
    from agent.livekit_minimal.agent import VachanamAgent

    src = inspect.getsource(VachanamAgent.confirm_booking)
    assert "caller_asked_to_book = False" in src.split("any_booking_confirmed = True")[1]


def test_the_default_is_still_unseeded():
    """An ordinary inbound call must earn its consent from the caller."""
    s = SessionState()
    assert s.caller_asked_to_book is False
    assert s.caller_asked_to_reschedule is False
    assert s.caller_asked_to_cancel is False

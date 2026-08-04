"""A doctor pulling a patient in sooner MOVES the visit, never adds a second.

Vinay 2026-08-04: "if patient is in pain and doctor sees the reply and advised
to come next day itself instead of the mentioned day — will it reschedule?"

It could not. Three things were missing and all three are checked here:

1. The doctor had nowhere to put a new date. `ReplyIn.next_reporting_date`
   existed but `doctor_reply` dropped it on the floor, and the frontend never
   sent it.
2. The dispatcher stripped every date off a doctor_advice call — correctly for
   the NOTE's date (RULE 9: a booking hint belonging to the note must not ride
   an advice call), but that also silenced a date the doctor typed on purpose.
3. Nothing told the agent a booking might already exist, so with the date
   restored it would have called confirm_booking and left the patient holding
   two appointments — a worse outcome than the original bug.
"""
from datetime import date

import pytest


# ── 2. the dispatcher carries the doctor's date, not the note's ──────────────

class _Task:
    def __init__(self, task_type, target_date=None):
        self.task_type = task_type
        self.target_date = target_date
        self.id = "t1"
        self.what_to_ask = "How is the swelling?"


def _meta(task, note_date):
    """The metadata block from `_dispatch`, in isolation.

    Kept as a mirror of the real branch rather than a call into it: _dispatch
    talks to LiveKit, and what needs guarding is the DECISION, which is the
    part that regressed.
    """
    meta = {"call_type": task.task_type}
    if task.task_type == "next_visit_book":
        if note_date:
            meta["target_date"] = note_date
            meta["window"] = 2
    elif task.target_date:
        meta["target_date"] = task.target_date.isoformat()
        meta["window"] = 2
    return meta


def test_a_doctor_advice_call_carries_the_date_the_doctor_typed():
    tomorrow = date(2026, 8, 5)
    meta = _meta(_Task("doctor_advice", tomorrow), note_date="2026-08-15")
    assert meta["target_date"] == "2026-08-05", "the doctor's date must win"
    assert meta["window"] == 2


def test_a_doctor_advice_call_never_carries_the_notes_date():
    """RULE 9: the note's date belongs to the next_visit_book task. An advice
    call with no date of its own must stay silent about booking."""
    meta = _meta(_Task("doctor_advice", None), note_date="2026-08-15")
    assert "target_date" not in meta


def test_the_booking_call_still_uses_the_notes_date():
    meta = _meta(_Task("next_visit_book", None), note_date="2026-08-15")
    assert meta["target_date"] == "2026-08-15"


def test_a_doctors_date_does_not_hijack_the_booking_call():
    """Only doctor_advice reads task.target_date — next_visit_book's date is
    the note's, and mixing the two would silently move a booking nudge."""
    meta = _meta(_Task("next_visit_book", date(2026, 8, 5)), note_date="2026-08-15")
    assert meta["target_date"] == "2026-08-15"


# ── 3. the prompt moves a booking instead of adding one ──────────────────────

def _advice_prompt(target="the fifth of August (2026-08-05)"):
    from agent.livekit_minimal.agent import DOCTOR_ADVICE_PROMPT_EXTRA

    return DOCTOR_ADVICE_PROMPT_EXTRA.format(
        message="Please come in tomorrow instead.",
        doctor="Dr Srinivas",
        patient="Vinay",
        target_date=target,
    )


def test_the_advice_call_looks_for_an_existing_booking_first():
    p = _advice_prompt()
    assert "find_my_bookings" in p
    assert "reschedule_booking" in p


def test_the_advice_call_is_told_not_to_double_book():
    """The failure mode this whole change exists to prevent."""
    p = _advice_prompt().lower()
    assert "two appointments" in p
    assert "do not call confirm_booking" in p


def test_a_patient_with_no_booking_still_gets_one():
    p = _advice_prompt()
    assert "no upcoming booking" in p.lower() and "confirm_booking" in p


def test_the_patient_is_not_asked_who_they_are():
    p = _advice_prompt()
    assert "Vinay" in p
    assert "not ask their name" in p.lower() or "do not ask" in p.lower()


def test_the_time_is_always_the_patients_choice():
    p = _advice_prompt().lower()
    assert "never pick a time yourself" in p


def test_no_date_means_no_reschedule_instructions_fire():
    """With no date the relay is just a relay — the move branch is explicitly
    conditional so it cannot fire on an ordinary advice call."""
    p = _advice_prompt("(none — the doctor did not ask for a specific date)")
    assert "IF that date is present" in p
    assert "none —" in p


def test_the_relay_never_becomes_medical_advice():
    p = _advice_prompt().lower()
    assert "rule 7" in p or "invent any medical content" in p


# ── the first call now offers the visit however the patient answers ─────────

def _next_visit_prompt():
    from agent.livekit_minimal.agent import NEXT_VISIT_PROMPT_EXTRA

    return NEXT_VISIT_PROMPT_EXTRA.format(
        message="How is the swelling?",
        doctor="Dr Srinivas",
        patient="Vinay",
        target_date="the fifteenth of August (2026-08-15)",
    )


def test_a_patient_in_pain_is_still_offered_the_visit():
    """Vinay 2026-08-04, superseding his 2026-07-03 rule: without a booking
    there is nothing for the doctor to move when they read the report."""
    p = _next_visit_prompt().lower()
    assert "still offer the visit" in p
    assert "only on a good report" not in p


def test_the_problem_still_reaches_the_doctor():
    p = _next_visit_prompt().lower()
    assert "inform the doctor" in p


def test_offering_a_visit_is_not_dressed_up_as_treatment():
    """RULE 7 holds: offer the slot, never claim it helps or that it can wait."""
    p = _next_visit_prompt().lower()
    assert "never say the appointment will fix anything" in p
    assert "no diagnosis" in p


def test_a_refusal_is_accepted():
    p = _next_visit_prompt().lower()
    assert "if they say no" in p


@pytest.mark.parametrize("prompt_fn", [_advice_prompt, _next_visit_prompt])
def test_neither_prompt_leaks_an_unformatted_placeholder(prompt_fn):
    p = prompt_fn()
    assert "{" not in p and "}" not in p

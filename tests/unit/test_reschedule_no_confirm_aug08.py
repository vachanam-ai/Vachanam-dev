"""A reschedule happens on the first ask. No confirmation question, ever.

Vinay 2026-08-08, third report of the same loop: "rescheduling is worst. asking
for confirmation n number of times. please fix it to ask just once. (or better
not ask for confirmation at all from conversation book). (please reschedule to
11am tomorrow -> done)."

#497 tried to fix it by widening the phrase list. It did not work, and this is
why — every one of these returned False from the recognition predicate:

    "repu 11 gantalaki marchandi"       Telugu in LATIN letters, which is what
    "time change cheyandi"              Soniox actually returns
    "appointment ni marchandi"
    "రీషెడ్యూల్ చేయండి"                 "reschedule" transliterated into Telugu

So the request was never recognised as a request, the sticky flag was never
set, and the guard fell through to matching the model's freely-worded question
against five hardcoded strings — which is the loop. #492 reached exactly this
conclusion for confirm_booking and stopped trying to recognise agreement;
reschedule kept a phrase list and therefore kept the bug. Third time now.

The gate is gone. What stays deterministic is a flat refusal, which is
exact-match over a multilingual set and does not care about script.
"""
import inspect

from agent.livekit_minimal.agent import (
    VachanamAgent,
    _caller_authorized_reschedule,
    _caller_refused_outright,
    _caller_withdrew_reschedule,
)

SRC = inspect.getsource(VachanamAgent.reschedule_booking)
# Everything before the write is the whole authorization surface. Comments are
# stripped because the block explains at length WHICH predicates it no longer
# calls — naming them in prose must not read as calling them.
GATE = "\n".join(
    line for line in SRC.split("_guard_human_booking")[0].splitlines()
    if not line.lstrip().startswith("#")
)


# ── the loop is gone by construction ─────────────────────────────────────────

def test_nothing_can_order_a_confirmation_question():
    """The loop's fuel was the guard's own ToolError telling the model to ask
    again. No re-ask instruction can exist here any more."""
    low = GATE.lower()
    for phrase in ("shall i move", "ask one short question", "not authorized yet",
                   "call reschedule_booking again"):
        assert phrase not in low, f"guard still orders a re-ask: {phrase!r}"


def test_the_phrase_list_no_longer_gates_the_write():
    """_caller_authorized_reschedule may still exist for the sticky flag, but a
    reschedule must not depend on it — that dependency IS the bug."""
    assert "_caller_authorized_reschedule" not in GATE
    assert "_last_assistant_requested_reschedule" not in GATE
    assert "caller_asked_to_reschedule or" not in GATE


def test_only_a_whole_turn_withdrawal_still_blocks():
    assert "_caller_withdrew_reschedule" in GATE


# ── the phrasings that were broken in production ─────────────────────────────

BROKEN_IN_PROD = [
    "repu 11 gantalaki marchandi",
    "time change cheyandi",
    "appointment ni marchandi",
    "kal 11 baje kar dijiye",
    "రేపు పదకొండు గంటలకు రీషెడ్యూల్ చేయండి",
    "please reschedule to 11am tomorrow",
    "రేపు 11 గంటలకు మార్చండి",
]


def test_every_real_phrasing_now_reaches_the_write():
    """None of these is blocked, whether or not the old predicate liked it.
    Four of the seven used to fail — which is why it looped."""
    for said in BROKEN_IN_PROD:
        assert not _caller_refused_outright(said), said


def test_the_ones_that_used_to_fail_really_did_fail():
    """Pins the pre-fix behaviour so nobody 'restores' the phrase list thinking
    it worked. If this ever goes green the predicate silently got better and
    this test should be re-read, not deleted."""
    unrecognised = [s for s in BROKEN_IN_PROD if not _caller_authorized_reschedule(s)]
    assert "repu 11 gantalaki marchandi" in unrecognised
    assert "time change cheyandi" in unrecognised
    assert "appointment ni marchandi" in unrecognised


# ── a no is still a no ───────────────────────────────────────────────────────

def test_a_flat_no_stops_the_move():
    for said in ("no", "nahi", "వద్దు", "vaddu"):
        assert _caller_refused_outright(said), said


def test_a_no_inside_a_yes_does_not_stop_it():
    """Exact-match, not substring — #492's "now" contains "no" bug."""
    for said in ("no problem, move it", "move it now", "nahi nahi kar dijiye"):
        assert not _caller_refused_outright(said), said


def test_whole_turn_withdrawals_block_without_eating_corrections():
    for said in (
        "I don't want to reschedule",
        "I do not want to move my appointment",
        "never mind",
        "keep it as it is",
        "actually leave it",
    ):
        assert _caller_withdrew_reschedule(said), said
    for said in (
        "nahi nahi kar dijiye",
        "not tomorrow, Friday",
        "not urgent, move it to Friday",
        "I don't want tomorrow; move it to Friday",
    ):
        assert not _caller_withdrew_reschedule(said), said


def test_cancel_keeps_its_confirmation():
    """Deliberate asymmetry. A wrongly-moved appointment still leaves the
    patient with a slot; a wrongly-cancelled one does not."""
    cancel = inspect.getsource(VachanamAgent.cancel_booking)
    gate = cancel.split("_guard_human_booking")[0]
    assert "_caller_affirmed" in gate or "caller_asked_to_cancel" in gate


def test_the_prompt_does_not_ask_either():
    """Removing the guard's re-ask is not enough if the prompt still tells it
    to confirm — that would be one question instead of none."""
    from agent.prompts.system_prompt import build_system_prompt

    prompt = build_system_prompt("Test", [], "", "clinic", language="en")
    assert "Never ask them to confirm a reschedule" in prompt

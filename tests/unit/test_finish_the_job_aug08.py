"""The agent finishes the job. Only the patient hangs up early.

Vinay 2026-08-08: "Call should never end before booking / rescheduling /
cancelling appointments. It should do the part else they can hang up."

#501 fixed this for booking alone, which was the instance in front of me at the
time. The rule is about the WORK — a half-finished reschedule and a
half-finished cancellation strand a patient exactly as badly as a half-finished
booking, and neither was covered.

Two independent signals, because each covers the other's blind spot:

    caller_asked_to_*    read from the caller's WORDS, so it inherits #502's
                         hole — "repu 11 gantalaki marchandi" sets nothing
    mutation_in_flight   set by the agent entering its own tool, so it does not
                         care what language anybody is speaking

Intent stated before any tool ran is caught by the first. A tool begun and
never finished is caught by the second. Belt and braces on purpose: a guard
resting only on utterance recognition would have shipped with the same Telugu
blind spot that caused the bug it is meant to prevent.
"""
import inspect
from types import SimpleNamespace

import pytest

from agent.livekit_minimal.agent import VachanamAgent, _tracks_mutation
from agent.session_state import SessionState

check = VachanamAgent._check_end_allowed


def _blocked(state, abandon=False) -> bool:
    try:
        check(state, abandon)
        return False
    except Exception:
        return True


# ── the three jobs must all be finished ──────────────────────────────────────

@pytest.mark.parametrize("state,what", [
    (SessionState(caller_asked_to_book=True), "booking asked for"),
    (SessionState(caller_asked_to_reschedule=True), "reschedule asked for"),
    (SessionState(caller_asked_to_cancel=True), "cancellation asked for"),
    (SessionState(mutation_in_flight="book"), "booking underway"),
    (SessionState(mutation_in_flight="reschedule"), "reschedule underway"),
    (SessionState(mutation_in_flight="cancel"), "cancellation underway"),
    (SessionState(token_held=True, token_confirmed=False), "token held"),
])
def test_the_call_cannot_end_with_unfinished_work(state, what):
    assert _blocked(state), f"hung up with a {what}"


def test_the_language_independent_signal_stands_alone():
    """The whole point: this fires with every utterance-derived flag false,
    which is the state a Latin-script Telugu caller actually produces."""
    s = SessionState(mutation_in_flight="reschedule")
    assert s.caller_asked_to_reschedule is False
    assert s.caller_asked_to_book is False
    assert s.token_held is False
    assert _blocked(s)


# ── and must be released when the work is done ───────────────────────────────

@pytest.mark.parametrize("state", [
    SessionState(),
    SessionState(token_held=True, token_confirmed=True, any_booking_confirmed=True),
    SessionState(mutation_in_flight=None),
])
def test_a_finished_call_still_ends(state):
    """The guard must not become its own outage."""
    assert not _blocked(state)


def test_the_patient_calling_it_off_releases_everything():
    """A flat no clears all four flags, so "actually leave it" then goodbye
    ends the call with no abandon flag needed."""
    s = SessionState(
        caller_asked_to_book=True, caller_asked_to_reschedule=True,
        caller_asked_to_cancel=True, mutation_in_flight="book",
    )
    # exactly what on_user_turn_completed does on _caller_refused_outright
    s.caller_asked_to_book = False
    s.caller_asked_to_reschedule = False
    s.caller_asked_to_cancel = False
    s.mutation_in_flight = None
    assert not _blocked(s)


def test_abandon_still_overrides_every_signal():
    s = SessionState(
        caller_asked_to_cancel=True, mutation_in_flight="cancel", token_held=True,
    )
    assert not _blocked(s, abandon=True)


# ── the flag is actually maintained, not just declared ───────────────────────

SRC = inspect.getsource(VachanamAgent)


@pytest.mark.parametrize("tool,value", [
    ("confirm_booking", "book"),
    ("reschedule_booking", "reschedule"),
    ("cancel_booking", "cancel"),
])
def test_each_mutation_marks_itself_underway(tool, value):
    src = inspect.getsource(getattr(VachanamAgent, tool))
    assert f"@_tracks_mutation('{value}')" in src, (
        f"{tool} never marks itself in flight, so the call can end in the "
        f"middle of it"
    )


@pytest.mark.asyncio
async def test_mutation_tracker_restores_the_previous_flag_on_every_exit():
    """In-flight describes an executing coroutine, not a sticky retry intent."""
    target = SimpleNamespace(_state=SimpleNamespace(mutation_in_flight="outer"))
    observed = []

    @_tracks_mutation("book")
    async def operation(self, fail=False):
        observed.append(self._state.mutation_in_flight)
        if fail:
            raise RuntimeError("write failed")

    await operation(target)
    assert observed == ["book"]
    assert target._state.mutation_in_flight == "outer"

    with pytest.raises(RuntimeError, match="write failed"):
        await operation(target, fail=True)
    assert observed == ["book", "book"]
    assert target._state.mutation_in_flight == "outer"


def test_the_flag_is_marked_after_the_authorization_gate():
    """Marking BEFORE the gate would set it on a call the guard then refuses,
    leaving a mutation 'in flight' that never started."""
    src = inspect.getsource(VachanamAgent.cancel_booking)
    assert src.index("_guard_human_booking") < src.index('mutation_in_flight = "cancel"')


def test_a_refusal_clears_the_in_flight_flag_too():
    """Otherwise "no, leave it" would hold the line open for cancelled work."""
    turn = inspect.getsource(VachanamAgent.on_user_turn_completed)
    refusal = turn.split(
        "declined_turn = _caller_refused_outright(utterance)", 1
    )[1].split("else:", 1)[0]
    assert "mutation_in_flight = None" in refusal


def test_the_flag_starts_clear():
    assert SessionState().mutation_in_flight is None


# ── the patient's own escape route is untouched ──────────────────────────────

def test_silence_still_ends_a_call_the_guard_refuses():
    """The guard makes the AGENT finish the job. It must never be able to hold
    a caller who has already gone."""
    from agent.livekit_minimal import agent as agent_mod

    src = inspect.getsource(agent_mod.entrypoint)
    watchdog = src.split("_silence_watchdog")[1].split("_sil_task")[0]
    assert "delete_room" in watchdog
    assert "_check_end_allowed" not in watchdog


def test_the_end_log_records_every_signal():
    """When this next misfires, the log has to say WHICH flag held the line."""
    src = inspect.getsource(VachanamAgent.end_call)
    for field in ("asked_to_book", "asked_resched", "asked_cancel", "in_flight"):
        assert field in src
    assert "last_user_utterance" not in src, "RULE 9 — no spoken text in logs"

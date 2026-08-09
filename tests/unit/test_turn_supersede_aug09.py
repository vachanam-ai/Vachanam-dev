"""One question, one answer — and stopping means stopping.

Vinay 2026-08-09, live call, two separate complaints:

  1. "when i repeat question, before it replied. it is repeating answer 2 times."
  2. "when i am speaking when it talks the time it takes to go silent is high
     (1-2sec)."

DOUBLE ANSWER. LiveKit's interruption machinery guards the agent while it is
SPEAKING, and the backchannel filter in `stt_node` only suppresses while
`agent_state == "speaking"`. Neither covers "thinking" — so a repeat that lands
while the LLM is still generating is neither interrupted nor filtered, commits
as a second turn, and both replies play. `interrupt()` appeared exactly once in
the whole agent before this (inside `switch_language`); nothing cancelled a
pending reply.

SLOW STOP. `false_interruption_timeout` was never set, so it ran on LiveKit's
2.0s default — the window the session waits for a SECOND word before deciding
an interruption was real. VAD pauses the audio at once, but for up to two
seconds the agent can still call it a false alarm and RESUME. That resume is
what a caller hears as "it took ages to stop". Kept #403's `min_words=2` (a
lone "హలో?" must never cut a confirmation short) and shortened the window
instead.
"""
import inspect

import pytest

from agent.livekit_minimal import agent as agent_mod
from agent.livekit_minimal.agent import VachanamAgent

SRC = inspect.getsource(VachanamAgent.on_user_turn_completed)
ENTRY = inspect.getsource(agent_mod.entrypoint)


# ── one answer per question ──────────────────────────────────────────────────

def test_a_new_turn_cancels_a_reply_still_being_generated():
    assert "sess.interrupt()" in SRC, (
        "a turn committed mid-generation leaves the previous reply queued, so "
        "the caller hears the same answer twice"
    )


def test_it_cancels_while_thinking_not_only_while_speaking():
    """The whole bug lives in the "thinking" window — guarding only "speaking"
    reproduces it exactly."""
    window = SRC.split("sess.interrupt()")[0]
    assert '"thinking"' in window
    assert '"speaking"' in window


def test_the_cancel_happens_before_anything_generates():
    """Cancelling after the new reply started would cut off the new answer
    instead of the stale one."""
    assert SRC.index("sess.interrupt()") < SRC.index("caller_asked_to_book")


def test_a_failed_cancel_never_drops_the_turn():
    """RULE 8. Losing a real patient turn is far worse than a doubled answer."""
    window = SRC.split("sess.interrupt()")[1].split("Remember consent")[0]
    assert "except Exception" in window


def test_the_supersede_is_logged():
    """So the next real call can prove whether it fired."""
    assert "superseded_pending_reply" in SRC


def test_it_does_not_force_the_interrupt():
    """force=True would tear down mid-write; a normal cancel lets the in-flight
    generation unwind and keeps the chat context consistent."""
    call = SRC.split("sess.interrupt(")[1].split(")")[0]
    assert "force" not in call


# ── stopping means stopping ──────────────────────────────────────────────────

def test_the_false_interruption_window_is_shortened():
    assert '"false_interruption_timeout": 0.6' in ENTRY, (
        "unset means LiveKit's 2.0s default — the 1-2s Vinay reported"
    )


def test_403_is_not_reopened():
    """min_words=2 is what stops a lone "హలో?" or "haan" cutting the agent off
    mid-confirmation. Shortening the window must not have traded that away."""
    block = ENTRY.split('"interruption": {')[1].split("}")[0]
    assert '"min_words": 2' in block
    assert '"resume_false_interruption": True' in block


def test_the_window_leaves_room_for_the_transcript():
    """Soniox interims land in ~0.1-0.3s. The window has to comfortably exceed
    that or real interruptions get misread as false and the agent resumes."""
    block = ENTRY.split('"interruption": {')[1].split("}")[0]
    value = float(block.split('"false_interruption_timeout":')[1].split(",")[0])
    assert 0.4 <= value < 2.0, f"{value}s is outside the useful range"


@pytest.mark.parametrize("knob,expected", [
    ("min_duration", "0.4"),
    ("min_words", "2"),
])
def test_the_other_interruption_knobs_are_untouched(knob, expected):
    """One control at a time — #399's lesson was that combined aggressive knobs
    corrupted Telugu recognition."""
    block = ENTRY.split('"interruption": {')[1].split("}")[0]
    assert f'"{knob}": {expected}' in block

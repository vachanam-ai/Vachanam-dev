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

SLOW STOP. The false-interruption timeout was never set, so it ran on LiveKit's
2.0s default. VAD pauses the audio at once, but for up to two seconds the agent
can still call it a false alarm and RESUME. The timeout is now short, and the
STT backchannel filter protects hello/hmm while a one-word name or time can
interrupt.
"""
import asyncio
import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent.livekit_minimal import agent as agent_mod
from agent.livekit_minimal.agent import VachanamAgent
from agent.session_state import SessionState

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
    assert '"false_interruption_timeout": 0.45' in ENTRY, (
        "unset means LiveKit's 2.0s default — the 1-2s Vinay reported"
    )


def test_meaningful_one_word_correction_interrupts():
    """Names and times are often one-word corrections; the STT backchannel
    filter, not a two-word minimum, protects hello/haan/hmm."""
    block = ENTRY.split('"interruption": {')[1].split("}")[0]
    assert '"min_words": 1' in block
    assert '"resume_false_interruption": True' in block


def test_the_window_leaves_room_for_the_transcript():
    """Soniox interims land in ~0.1-0.3s. The window has to comfortably exceed
    that or real interruptions get misread as false and the agent resumes."""
    block = ENTRY.split('"interruption": {')[1].split("}")[0]
    value = float(block.split('"false_interruption_timeout":')[1].split(",")[0])
    assert 0.4 <= value < 2.0, f"{value}s is outside the useful range"


@pytest.mark.parametrize("knob,expected", [
    ("min_duration", "0.25"),
    ("min_words", "1"),
])
def test_the_other_interruption_knobs_are_untouched(knob, expected):
    """One control at a time — #399's lesson was that combined aggressive knobs
    corrupted Telugu recognition."""
    block = ENTRY.split('"interruption": {')[1].split("}")[0]
    assert f'"{knob}": {expected}' in block


def test_incomplete_fragment_has_a_cancellable_grace_window():
    assert "_defer_incomplete_clarification(" in SRC
    assert agent_mod.INCOMPLETE_CLARIFICATION_GRACE_S == 0.35
    assert '_cancel_deferred_clarification(state, "caller_resumed")' in ENTRY


@pytest.mark.asyncio
async def test_caller_resume_cancels_fragment_clarification_before_audio():
    state = SessionState()
    fake = SimpleNamespace(state=None, _state=state, session=SimpleNamespace(say=AsyncMock()))
    VachanamAgent._defer_incomplete_clarification(fake, "please continue")
    agent_mod._cancel_deferred_clarification(state, "caller_resumed")
    await asyncio.sleep(0)
    fake.session.say.assert_not_awaited()


@pytest.mark.asyncio
async def test_fragment_clarification_speaks_after_grace(monkeypatch):
    monkeypatch.setattr(agent_mod, "INCOMPLETE_CLARIFICATION_GRACE_S", 0)
    state = SessionState()
    fake = SimpleNamespace(state=None, _state=state, session=SimpleNamespace(say=AsyncMock()))
    VachanamAgent._defer_incomplete_clarification(fake, "please continue")
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    fake.session.say.assert_awaited_once_with(
        "please continue", allow_interruptions=True
    )

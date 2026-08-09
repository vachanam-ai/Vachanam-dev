"""Hanging up on a question is the worst thing this agent can do.

Vinay 2026-08-09, live call: "after booking appointment it asked, is there
anything i can help you with. i asked can you speak english, it said sure. i
asked i heard there are lot of specialities in your hospital can you describe.
it ended call without any reply."

Fly logs for room ...9ZWRzgrww92B are unambiguous — the question was heard,
transcribed, and thrown away:

    08:03:34  LLM + TTS          model calls end_call, goodbye starts playing
    08:03:38  STT metrics        the specialities question
    08:03:40  call_ended_by_agent
    08:03:40  skipping on_user_turn_completed, speech scheduling is paused
              user_input='So I heard, like, there is so many specialties…'

end_call committed the moment the model called it: say goodbye, wait for
playout, delete the room — deaf to the caller throughout. And "anything else?"
is *precisely* the moment a caller starts talking.

#504's guard does not cover this. That one blocks a hangup mid-MUTATION, and
the booking was finished. This is a different failure: the work was done, and
the caller had a new question.
"""
import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.livekit_minimal.agent import VachanamAgent
from agent.session_state import SessionState


def _agent(state):
    a = MagicMock(spec=VachanamAgent)
    a._state = state
    a._lang_code = "te"
    a._room = MagicMock()
    a._room.name = "call-test"
    return a


def _ctx(*, speaking_now=False, current_speech=None):
    ctx = MagicMock()
    ctx.session = MagicMock()
    ctx.session.current_speech = current_speech
    ctx.session.user_state = "speaking" if speaking_now else "listening"
    ctx.session.say = AsyncMock()
    ctx.wait_for_playout = AsyncMock()
    return ctx


async def _run(agent, ctx):
    """Call the real end_call past its @function_tool wrapper, with the LiveKit
    API stubbed so nothing tries to reach the network."""
    with pytest.MonkeyPatch.context() as mp:
        api = MagicMock()
        api.LiveKitAPI.return_value.room.delete_room = AsyncMock()
        api.LiveKitAPI.return_value.aclose = AsyncMock()
        mp.setattr("agent.livekit_minimal.agent.api", api)
        result = await VachanamAgent.end_call.__wrapped__(agent, ctx)
        return result, api.LiveKitAPI.return_value.room.delete_room


# ── the reported call ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_question_during_the_goodbye_cancels_the_hangup():
    """The exact shape of the 08-09 call."""
    state = SessionState(any_booking_confirmed=True, token_confirmed=True)
    agent = _agent(state)
    ctx = _ctx()

    async def _speaks_during_playout():
        # The caller starts their question while the goodbye is playing.
        import time
        state.last_user_speech_at = time.monotonic()
    ctx.wait_for_playout = AsyncMock(side_effect=_speaks_during_playout)

    result, delete_room = await _run(agent, ctx)
    delete_room.assert_not_awaited()
    assert result["aborted"] is True
    assert result["success"] is False


@pytest.mark.asyncio
async def test_a_caller_mid_sentence_right_now_cancels_the_hangup():
    """Second signal: they are still talking as the goodbye ends, so the VAD
    edge may not have landed on the state yet."""
    agent = _agent(SessionState(any_booking_confirmed=True))
    result, delete_room = await _run(agent, _ctx(speaking_now=True))
    delete_room.assert_not_awaited()
    assert result["aborted"] is True


@pytest.mark.asyncio
async def test_the_abort_tells_the_model_to_answer():
    """A bare failure would leave the model guessing; it has to know to reply."""
    agent = _agent(SessionState())
    result, _ = await _run(agent, _ctx(speaking_now=True))
    low = result["instruction"].lower()
    assert "do not end the call" in low
    assert "answer" in low


# ── a genuinely finished call must still end ─────────────────────────────────

@pytest.mark.asyncio
async def test_a_silent_caller_still_gets_hung_up_on():
    """The guard must not become an outage of its own — 'nothing, thank you'
    followed by silence has to end the call (Vinay 08-07)."""
    agent = _agent(SessionState(any_booking_confirmed=True, token_confirmed=True))
    result, delete_room = await _run(agent, _ctx())
    delete_room.assert_awaited_once()
    assert result["success"] is True


@pytest.mark.asyncio
async def test_speech_from_BEFORE_the_hangup_does_not_block_it():
    """Every caller has spoken at some point — only speech AFTER end_call began
    counts, or the agent could never hang up at all."""
    import time
    state = SessionState(any_booking_confirmed=True)
    state.last_user_speech_at = time.monotonic() - 30.0   # half a minute ago
    result, delete_room = await _run(_agent(state), _ctx())
    delete_room.assert_awaited_once()
    assert result["success"] is True


# ── ordering and wiring ──────────────────────────────────────────────────────

def test_the_abort_check_runs_after_the_goodbye_finishes_playing():
    """Checking before playout would miss the whole window that matters — the
    caller talks DURING the goodbye."""
    src = inspect.getsource(VachanamAgent.end_call)
    assert src.index("wait_for_playout") < src.index("_spoke_during_goodbye")
    assert src.index("_spoke_during_goodbye") < src.index("delete_room")


def test_the_mutation_guard_still_runs_first():
    """#504 blocks a hangup mid-booking; this abort is additional, not a
    replacement. The guard must stay the first thing end_call does."""
    src = inspect.getsource(VachanamAgent.end_call)
    assert src.index("_check_end_allowed") < src.index("_end_started")


def test_the_session_records_when_the_caller_last_spoke():
    """The abort is only as good as the signal feeding it."""
    from agent.livekit_minimal import agent as agent_mod

    handler = inspect.getsource(agent_mod.entrypoint).split("_on_user_state")[1]
    handler = handler.split("_silence_watchdog")[0]
    assert "state.last_user_speech_at" in handler


def test_the_timestamp_starts_unset():
    assert SessionState().last_user_speech_at == 0.0

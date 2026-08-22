import asyncio
from types import SimpleNamespace

import pytest
from livekit.agents import StopResponse

from agent.livekit_minimal import agent as agent_mod
from agent.livekit_minimal.agent import (
    _guard_internal_speech_stream,
    _guard_output_language_with_verified_receipt,
    _guard_unbacked_checking_speech_stream,
    _guard_unverified_action_speech_stream,
    _settle_read_answer_stream,
    _tracks_read,
)
from agent.livekit_minimal.confirm_speech import build_read_failure_text
from agent.session_state import SessionState


class _Session:
    def __init__(self):
        self.said = []

    def say(self, text, **kwargs):
        self.said.append((text, kwargs))


async def _text_stream(text: str, width: int):
    for index in range(0, len(text), width):
        yield text[index:index + width]


async def _spoken(text: str, width: int, state: SessionState) -> str:
    stream = _guard_unbacked_checking_speech_stream(
        _text_stream(text, width), "en", state
    )
    stream = _guard_internal_speech_stream(stream)
    stream = _guard_unverified_action_speech_stream(
        stream, "en", verified_state=state
    )
    stream = _guard_output_language_with_verified_receipt(
        stream, "en", None, state
    )
    return "".join([
        chunk
        async for chunk in _settle_read_answer_stream(
            stream, state
        )
    ])


@pytest.mark.asyncio
@pytest.mark.parametrize("width", (1, 2, 3))
async def test_direct_read_failure_is_terminal_before_late_model_speech(
    monkeypatch,
    width,
):
    state = SessionState(
        language="en",
        last_user_utterance="When is Dr Rao available?",
    )
    session = _Session()
    owner = SimpleNamespace(_state=state, _lang_code="en")
    context = SimpleNamespace(session=session)
    monkeypatch.setattr(agent_mod, "AgentSession", _Session)

    @_tracks_read
    async def broken_read(_owner, _context):
        raise RuntimeError("backend offline")

    with pytest.raises(StopResponse):
        await broken_read(owner, context)

    failure = build_read_failure_text("en")
    assert session.said == [(failure, {})]
    assert state.pending_clinic_message is not None
    assert "When is Dr Rao available?" in state.pending_clinic_message
    assert "no booking or other action was confirmed" in state.pending_clinic_message
    assert await _spoken(failure, width, state) == failure
    assert await _spoken(
        "Dr Rao is available at 5 PM. Your appointment is booked.",
        width,
        state,
    ) == ""
    assert state.read_terminal_failure_armed is True


@pytest.mark.asyncio
@pytest.mark.parametrize("width", (1, 2, 3))
async def test_terminal_read_failure_receipt_is_one_use(monkeypatch, width):
    state = SessionState(language="en", last_user_utterance="Please check.")
    session = _Session()
    owner = SimpleNamespace(_state=state, _lang_code="en")
    context = SimpleNamespace(session=session)
    monkeypatch.setattr(agent_mod, "AgentSession", _Session)

    @_tracks_read
    async def broken_read(_owner, _context):
        raise RuntimeError("backend offline")

    with pytest.raises(StopResponse):
        await broken_read(owner, context)

    failure = build_read_failure_text("en")
    assert await _spoken(failure, width, state) == failure
    assert await _spoken(failure, width, state) == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("width", (1, 2, 3))
async def test_empty_reply_fallback_suppresses_generation_that_finishes_late(
    monkeypatch,
    width,
):
    state = SessionState(
        language="en",
        last_user_utterance="When is Dr Rao available?",
    )
    session = _Session()
    owner = SimpleNamespace(_state=state, _lang_code="en")
    context = SimpleNamespace(session=session)
    fallback_release = asyncio.Event()
    fallback_delays = []
    model_started = asyncio.Event()
    model_release = asyncio.Event()
    real_sleep = asyncio.sleep

    async def controlled_sleep(_seconds):
        fallback_delays.append(_seconds)
        await fallback_release.wait()

    monkeypatch.setattr(agent_mod, "AgentSession", _Session)
    monkeypatch.setattr(agent_mod.asyncio, "sleep", controlled_sleep)

    @_tracks_read
    async def successful_read(_owner, _context):
        return {"doctor": "Dr Rao", "time": "17:00"}

    await successful_read(owner, context)
    await real_sleep(0)
    assert fallback_delays == [agent_mod._READ_RESULT_SPEECH_GRACE_SECONDS]
    assert fallback_delays[0] >= 8.0

    async def late_model_source():
        model_started.set()
        await model_release.wait()
        async for chunk in _text_stream(
            "Dr Rao is available at 2:30 PM.", width
        ):
            yield chunk

    late_model = asyncio.create_task(
        _spoken_from_stream(late_model_source(), state)
    )
    await model_started.wait()
    fallback_release.set()
    for _ in range(20):
        if state.read_terminal_failure_armed:
            break
        await real_sleep(0)

    failure = build_read_failure_text("en")
    assert session.said == [(failure, {})]
    assert state.pending_clinic_message is not None
    assert "When is Dr Rao available?" in state.pending_clinic_message
    assert await _spoken(failure, width, state) == failure
    model_release.set()
    assert await late_model == ""


async def _spoken_from_stream(stream, state: SessionState) -> str:
    stream = _guard_unbacked_checking_speech_stream(stream, "en", state)
    stream = _guard_internal_speech_stream(stream)
    stream = _guard_unverified_action_speech_stream(
        stream, "en", verified_state=state
    )
    stream = _guard_output_language_with_verified_receipt(
        stream, "en", None, state
    )
    return "".join([
        chunk async for chunk in _settle_read_answer_stream(stream, state)
    ])

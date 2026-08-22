import pytest

from agent.livekit_minimal.agent import (
    _read_result_evidence,
    _settle_read_answer_stream,
)
from agent.session_state import SessionState


async def _text_stream(text: str, width: int):
    for index in range(0, len(text), width):
        yield text[index:index + width]


async def _collect_stream(stream) -> str:
    return "".join([chunk async for chunk in stream])


@pytest.mark.asyncio
@pytest.mark.parametrize("width", (1, 2, 3))
async def test_token_capacity_polarity_cannot_be_reversed(width):
    availability = (
        "Doctor has 2 patients booked on 28 August. Published sitting sessions: "
        "05:00 PM to 09:00 PM. Capacity remains, but no token is reserved or "
        "assigned until the booking write succeeds."
    )
    state = SessionState(
        language="en",
        read_answer_owed=True,
        read_owed_utterance="Is there token capacity on 28 August?",
        read_result_evidence=_read_result_evidence(
            {"availability": availability}, "en"
        ),
    )

    spoken = await _collect_stream(
        _settle_read_answer_stream(
            _text_stream("There is no capacity on 28 August.", width), state
        )
    )

    assert spoken == ""
    assert state.read_answer_owed is True


@pytest.mark.asyncio
@pytest.mark.parametrize("speech", (
    "Capacity remains on 28 August.",
    "Capacity remains, but no token is assigned until booking succeeds.",
))
async def test_truthful_token_capacity_answer_reaches_the_caller(speech):
    availability = (
        "Doctor has 2 patients booked on 28 August. Published sitting sessions: "
        "05:00 PM to 09:00 PM. Capacity remains, but no token is reserved or "
        "assigned until the booking write succeeds."
    )
    state = SessionState(
        language="en",
        read_answer_owed=True,
        read_owed_utterance="Is there token capacity on 28 August?",
        read_result_evidence=_read_result_evidence(
            {"availability": availability}, "en"
        ),
    )

    spoken = await _collect_stream(
        _settle_read_answer_stream(_text_stream(speech, 1), state)
    )

    assert spoken == speech
    assert state.read_answer_owed is False


@pytest.mark.asyncio
async def test_token_unassigned_does_not_answer_a_capacity_question():
    availability = (
        "Doctor has 2 patients booked on 28 August. Published sitting sessions: "
        "05:00 PM to 09:00 PM. Capacity remains, but no token is reserved or "
        "assigned until the booking write succeeds."
    )
    state = SessionState(
        language="en",
        read_answer_owed=True,
        read_owed_utterance="Is there token capacity on 28 August?",
        read_result_evidence=_read_result_evidence(
            {"availability": availability}, "en"
        ),
    )

    spoken = await _collect_stream(
        _settle_read_answer_stream(
            _text_stream("No token is assigned yet.", 1), state
        )
    )

    assert spoken == ""
    assert state.read_answer_owed is True


@pytest.mark.asyncio
@pytest.mark.parametrize("width", (1, 2, 3))
async def test_exact_unfree_window_truth_reaches_the_caller(width):
    availability = (
        "Requested window is NOT free. There is no free start between "
        "5:00 PM and 5:30 PM. NEAREST free times to their request: 5:45 PM. "
        "All BOOKABLE APPOINTMENT STARTS: 5:45 PM on 28 August."
    )
    speech = (
        "There is no free start between 5 PM and 5:30 PM. "
        "5:45 PM is free."
    )
    state = SessionState(
        language="en",
        read_answer_owed=True,
        read_owed_utterance="Is the 5 PM to 5:30 PM window free?",
        read_result_evidence=_read_result_evidence(
            {"availability": availability}, "en"
        ),
    )

    spoken = await _collect_stream(
        _settle_read_answer_stream(_text_stream(speech, width), state)
    )

    assert spoken == speech
    assert state.read_answer_owed is False


@pytest.mark.asyncio
async def test_truthful_unavailable_contraction_reaches_the_caller():
    result = {
        "doctor": "Dr Rao",
        "date": "2026-08-28",
        "available": False,
    }
    speech = "Dr Rao isn't available on 28 August."
    state = SessionState(
        language="en",
        read_answer_owed=True,
        read_owed_utterance="Is Dr Rao available on 28 August?",
        read_result_evidence=_read_result_evidence(result, "en"),
    )

    spoken = await _collect_stream(
        _settle_read_answer_stream(_text_stream(speech, 1), state)
    )

    assert spoken == speech
    assert state.read_answer_owed is False

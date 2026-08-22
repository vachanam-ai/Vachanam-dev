import pytest

from agent.livekit_minimal.agent import (
    _read_result_evidence,
    _settle_read_answer_stream,
)
from agent.session_state import SessionState


async def _text_stream(text: str, width: int):
    for index in range(0, len(text), width):
        yield text[index:index + width]


async def _settle(result: dict, question: str, speech: str, width: int):
    state = SessionState(
        language="en",
        read_answer_owed=True,
        read_owed_utterance=question,
        read_result_evidence=_read_result_evidence(result, "en"),
    )
    spoken = "".join([
        chunk
        async for chunk in _settle_read_answer_stream(
            _text_stream(speech, width), state
        )
    ])
    return spoken, state


_BOOKING = {
    "bookings": [{
        "patient_name": "Asha",
        "doctor": "Dr Rao",
        "date": "2026-08-28",
        "time": "17:00",
    }]
}
_BOOKING_FACT = (
    "The appointment under Asha is with Dr Rao on 28 August at 5 PM."
)


@pytest.mark.asyncio
@pytest.mark.parametrize("width", (1, 2, 3))
@pytest.mark.parametrize("false_tail", (
    " This is also for Bina.",
    " The provider is Patel.",
    " Patel will see you too.",
    " Bina also holds this booking.",
))
async def test_contextual_names_cannot_launder_through_a_true_booking(
    width,
    false_tail,
):
    spoken, state = await _settle(
        _BOOKING,
        "What is my appointment?",
        _BOOKING_FACT + false_tail,
        width,
    )

    assert spoken == ""
    assert state.read_answer_owed is True


@pytest.mark.asyncio
@pytest.mark.parametrize("width", (1, 2, 3))
@pytest.mark.parametrize("false_tail", (
    " Your provider is Patel.",
    " You can see Patel as well.",
))
async def test_titleless_provider_name_must_match_the_route_result(
    width,
    false_tail,
):
    result = {"doctor_name": "Dr Rao", "specialization": "Dermatology"}
    spoken, state = await _settle(
        result,
        "Which doctor treats skin problems?",
        "Dr Rao is a dermatologist." + false_tail,
        width,
    )

    assert spoken == ""
    assert state.read_answer_owed is True


@pytest.mark.asyncio
@pytest.mark.parametrize("width", (1, 2, 3))
@pytest.mark.parametrize("speech", (
    _BOOKING_FACT + " This is also for Asha.",
    _BOOKING_FACT + " The provider is Rao.",
))
async def test_contextual_grounded_names_still_reach_the_caller(width, speech):
    spoken, state = await _settle(
        _BOOKING,
        "What is my appointment?",
        speech,
        width,
    )

    assert spoken == speech
    assert state.read_answer_owed is False

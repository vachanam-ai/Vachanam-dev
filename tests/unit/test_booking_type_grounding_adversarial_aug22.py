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


_SLOT_RESULT = {
    "bookings": [{
        "patient_name": "Asha",
        "doctor": "Dr Rao",
        "date": "2026-08-28",
        "time": "17:00",
        "token_number": None,
        "booking_type": "appointment",
    }]
}
_SLOT_FACT = (
    "The appointment under Asha is with Dr Rao on 28 August at 5 PM."
)
_TOKEN_RESULT = {
    "bookings": [{
        "patient_name": "Asha",
        "doctor": "Dr Queue",
        "date": "2026-08-28",
        "time": None,
        "token_number": 7,
        "booking_type": "token",
    }]
}
_TOKEN_FACT = (
    "The appointment under Asha is with Dr Queue on 28 August, token number 7."
)


@pytest.mark.asyncio
@pytest.mark.parametrize("width", (1, 2, 3))
@pytest.mark.parametrize("false_tail", (
    " This is a token-queue booking.",
    " You are seventh in the token queue.",
    " You have a queue token.",
    " You received token 7.",
    " Your place in line is seventh.",
    " You are in the walk-in queue.",
    " This visit is first-come, first-served.",
    " There is no scheduled clock time.",
))
async def test_slot_booking_cannot_be_called_a_token_queue(
    width,
    false_tail,
):
    spoken, state = await _settle(
        _SLOT_RESULT,
        "What is my appointment?",
        _SLOT_FACT + false_tail,
        width,
    )

    assert spoken == ""
    assert state.read_answer_owed is True


@pytest.mark.asyncio
@pytest.mark.parametrize("width", (1, 2, 3))
@pytest.mark.parametrize("false_tail", (
    " This is a fixed-time slot.",
    " Your visit has a fixed appointment time.",
    " Your appointment is at lunchtime.",
    " This visit is not in the token queue.",
    " No token was issued for this visit.",
    " Your visit is scheduled for lunchtime.",
    " You have an exact appointment time.",
))
async def test_token_booking_cannot_be_called_a_fixed_time_slot(
    width,
    false_tail,
):
    spoken, state = await _settle(
        _TOKEN_RESULT,
        "What is my appointment?",
        _TOKEN_FACT + false_tail,
        width,
    )

    assert spoken == ""
    assert state.read_answer_owed is True


@pytest.mark.asyncio
@pytest.mark.parametrize("width", (1, 2, 3))
@pytest.mark.parametrize(("result", "speech"), (
    (
        _SLOT_RESULT,
        _SLOT_FACT + " This is a fixed-time slot, not a token queue.",
    ),
    (
        _TOKEN_RESULT,
        _TOKEN_FACT + " This is a token-queue booking with no scheduled time.",
    ),
))
async def test_truthful_booking_type_still_reaches_the_caller(
    width,
    result,
    speech,
):
    spoken, state = await _settle(
        result,
        "What is my appointment?",
        speech,
        width,
    )

    assert spoken == speech
    assert state.read_answer_owed is False


_TWO_TOKEN_RESULTS = {
    "bookings": [
        {
            "patient_name": "Asha",
            "doctor": "Dr Rao",
            "date": "2026-08-28",
            "time": None,
            "token_number": 7,
            "booking_type": "token",
        },
        {
            "patient_name": "Bina",
            "doctor": "Dr Shah",
            "date": "2026-08-29",
            "time": None,
            "token_number": 9,
            "booking_type": "token",
        },
    ]
}


@pytest.mark.asyncio
@pytest.mark.parametrize("width", (1, 2, 3))
@pytest.mark.parametrize("false_speech", (
    (
        "The appointment under Asha is with Dr Rao on 28 August, token "
        "number 9. The appointment under Bina is with Dr Shah on 29 August, "
        "token number 7."
    ),
    (
        "Token number 9 is for Asha with Dr Rao on 28 August. Token number "
        "7 is for Bina with Dr Shah on 29 August."
    ),
))
async def test_token_numbers_cannot_swap_between_booking_records(
    width,
    false_speech,
):
    spoken, state = await _settle(
        _TWO_TOKEN_RESULTS,
        "What are all my appointments?",
        false_speech,
        width,
    )

    assert spoken == ""
    assert state.read_answer_owed is True


@pytest.mark.asyncio
@pytest.mark.parametrize("width", (1, 2, 3))
async def test_truthful_token_number_mapping_still_reaches_the_caller(width):
    speech = (
        "The appointment under Asha is with Dr Rao on 28 August, token number "
        "7. The appointment under Bina is with Dr Shah on 29 August, token "
        "number 9."
    )
    spoken, state = await _settle(
        _TWO_TOKEN_RESULTS,
        "What are all my appointments?",
        speech,
        width,
    )

    assert spoken == speech
    assert state.read_answer_owed is False

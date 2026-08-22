"""Runtime regressions for slow voice reads and silence liveness.

All dependencies are fakes.  The watchdog test executes the nested production
coroutine from ``entrypoint`` so its suppression branch cannot drift from the
behavior exercised here.
"""

from __future__ import annotations

import asyncio
import inspect
import types
from contextlib import suppress
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from livekit.agents import StopResponse
from livekit.agents.llm import ChatContext

from agent.livekit_minimal import agent as agent_mod
from agent.livekit_minimal.agent import (
    VachanamAgent,
    _guard_internal_speech_stream,
    _guard_output_language_stream,
    _guard_output_language_with_verified_receipt,
    _guard_unbacked_checking_speech_stream,
    _guard_unverified_action_speech_stream,
    _read_result_evidence,
    _safe_output_recovery,
    _settle_read_answer_stream,
    _tracks_read,
)
from agent.livekit_minimal.confirm_speech import (
    build_no_booking_found_text,
    build_read_failure_text,
)
from agent.session_state import SessionState


READ_TOOLS = (
    "check_availability",
    "get_doctor_return_availability",
    "get_doctor_schedule",
    "find_my_bookings",
    "get_queue_status",
)


class _SessionAgent(VachanamAgent):
    @property
    def session(self):
        return self._test_session


class _ReadSession:
    def __init__(self) -> None:
        self.userdata = {
            "language": "en",
            "wait_clips": [],
            "wait_fillers": ("One moment, please. Let me check that.",),
        }
        self.said: list[tuple[str, dict]] = []

    def say(self, text: str, **kwargs):
        self.said.append((text, kwargs))
        return SimpleNamespace()


class _TickAsyncio:
    CancelledError = asyncio.CancelledError

    def __init__(self) -> None:
        self._ticks: asyncio.Queue[None] = asyncio.Queue()

    async def sleep(self, _seconds: float) -> None:
        await self._ticks.get()

    def tick(self) -> None:
        self._ticks.put_nowait(None)


class _WatchSession:
    agent_state = "listening"
    user_state = "listening"

    def __init__(self) -> None:
        self.said: list[tuple[str, dict]] = []
        self.spoke = asyncio.Event()

    async def say(self, text: str, **kwargs):
        self.said.append((text, kwargs))
        self.spoke.set()


def _agent(state: SessionState, *, session=None) -> VachanamAgent:
    cls = _SessionAgent if session is not None else VachanamAgent
    value = cls(
        instructions="test",
        state=state,
        db=None,
        room=None,
        # A connected slot calendar is the normal path for read-backend tests.
        # Tests for a disconnected calendar opt into ``None`` explicitly in the
        # dedicated mutation-outcome suite.
        calendar_service=object(),
        meta_service=None,
        transfer_to="",
        lang_code=state.language or "en",
    )
    if session is not None:
        value._test_session = session
    return value


def _message(text: str):
    return SimpleNamespace(text_content=text, content=text, role="user")


def _cell(value):
    return (lambda: value).__closure__[0]


async def _text_stream(text: str, chunk_size: int):
    for start in range(0, len(text), chunk_size):
        yield text[start : start + chunk_size]


async def _collect_stream(stream) -> str:
    return "".join([chunk async for chunk in stream])


async def _production_speech_boundary(
    speech: str,
    state: SessionState,
    *,
    chunk_size: int = 1,
) -> str:
    """Exercise the same ordered patient-facing guards as ``tts_node``."""
    language = state.language or "en"
    stream = _guard_unbacked_checking_speech_stream(
        _text_stream(speech, chunk_size), language, state
    )
    stream = _guard_internal_speech_stream(stream)
    receipt = state.verified_mutation_speech or state.verified_read_speech
    pending_action = (
        state.mutation_in_flight
        or state.pending_confirmation
        or ("cancel" if state.caller_asked_to_cancel else None)
        or ("reschedule" if state.caller_asked_to_reschedule else None)
        or ("booking" if state.caller_asked_to_book else None)
        or state.relay_snapshot_kind
    )
    stream = _guard_unverified_action_speech_stream(
        stream,
        language,
        verified_speech=receipt,
        verified_state=state,
        pending_action=pending_action,
    )
    stream = _guard_output_language_with_verified_receipt(
        stream, language, receipt, state
    )
    return await _collect_stream(_settle_read_answer_stream(stream, state))


def _watchdog_code() -> types.CodeType:
    for value in agent_mod.entrypoint.__code__.co_consts:
        if isinstance(value, types.CodeType) and value.co_name == "_silence_watchdog":
            return value
    raise AssertionError("production silence watchdog code was not found")


def _bound_watchdog(*, ticks, silence, session, state):
    code = _watchdog_code()
    closure_values = {
        "_perf": SimpleNamespace(monotonic=lambda: 11.0),
        "_sil": silence,
        "ctx": SimpleNamespace(room=SimpleNamespace(name="offline-test")),
        "lang_code": "en",
        "session": session,
        "state": state,
    }
    globals_ = agent_mod.__dict__.copy()
    globals_["asyncio"] = ticks
    return types.FunctionType(
        code,
        globals_,
        name=code.co_name,
        closure=tuple(_cell(closure_values[name]) for name in code.co_freevars),
    )


async def _eventually(predicate) -> None:
    for _ in range(100):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition did not become true")


def test_every_slow_patient_read_is_covered_by_the_shared_tracker():
    for tool_name in READ_TOOLS:
        source = inspect.getsource(getattr(VachanamAgent, tool_name))
        assert "@_tracks_read" in source, tool_name


@pytest.mark.asyncio
async def test_tracks_read_keeps_the_first_owed_turn_until_all_reads_finish():
    first_entered = asyncio.Event()
    second_entered = asyncio.Event()
    first_release = asyncio.Event()
    second_release = asyncio.Event()
    state = SessionState(
        language="en",
        last_user_utterance="When is Dr Rao available tomorrow?",
    )
    owner = SimpleNamespace(_state=state, _lang_code="en")
    context = SimpleNamespace(session=object())

    @_tracks_read
    async def first_read(_owner, _context):
        first_entered.set()
        await first_release.wait()
        return "first verified answer"

    @_tracks_read
    async def second_read(_owner, _context):
        second_entered.set()
        await second_release.wait()
        return "second verified answer"

    first = asyncio.create_task(first_read(owner, context))
    await first_entered.wait()
    assert state.read_in_flight_count == 1
    assert state.read_owed_utterance == "When is Dr Rao available tomorrow?"

    state.last_user_utterance = "And what is the live queue?"
    second = asyncio.create_task(second_read(owner, context))
    await second_entered.wait()
    assert state.read_in_flight_count == 2
    assert state.read_owed_utterance == "When is Dr Rao available tomorrow?"

    second_release.set()
    assert await second == "second verified answer"
    assert state.read_in_flight_count == 1
    assert state.read_owed_utterance == "When is Dr Rao available tomorrow?"

    first_release.set()
    assert await first == "first verified answer"
    assert state.read_in_flight_count == 0
    assert state.read_answer_owed is True
    assert state.read_owed_utterance == "When is Dr Rao available tomorrow?"


@pytest.mark.asyncio
@pytest.mark.parametrize("chunk_size", [1, 2, 3, 5, 1000])
async def test_truthful_read_answer_settles_identically_at_every_chunk_size(
    chunk_size,
):
    speech = "Dr Rao is available on 28 August at Five P.M."
    state = SessionState(
        language="en",
        read_answer_owed=True,
        read_owed_utterance="When is Dr Rao available?",
        read_result_evidence=_read_result_evidence(
            {
                "doctor_name": "Dr Rao",
                "date": "2026-08-28",
                "appointment_time": "17:00",
            },
            "en",
        ),
    )

    spoken = await _collect_stream(
        _settle_read_answer_stream(_text_stream(speech, chunk_size), state)
    )

    assert spoken == speech
    assert state.read_answer_owed is False
    assert state.read_owed_utterance is None
    assert state.read_result_evidence == ()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "preface",
    [
        "Okay.",
        "I found it.",
        "Here is what I found.",
        "The information is ready.",
    ],
)
async def test_generic_preface_cannot_settle_an_owed_read_answer(preface):
    state = SessionState(
        language="en",
        read_answer_owed=True,
        read_owed_utterance="When is Dr Rao available?",
        read_result_evidence=_read_result_evidence(
            {"doctor_name": "Dr Rao", "appointment_time": "17:00"}, "en"
        ),
    )

    spoken = await _collect_stream(
        _settle_read_answer_stream(_text_stream(preface, 1), state)
    )

    assert spoken == ""
    assert state.read_answer_owed is True
    assert state.read_owed_utterance == "When is Dr Rao available?"


@pytest.mark.asyncio
async def test_one_requested_time_can_settle_a_multi_slot_availability_result():
    speech = "Five P.M. is available."
    state = SessionState(
        language="en",
        read_answer_owed=True,
        read_owed_utterance="Is five P.M. available?",
        read_result_evidence=_read_result_evidence(
            {"availability": "17:00, 17:15, 17:30"}, "en"
        ),
    )

    spoken = await _collect_stream(
        _settle_read_answer_stream(_text_stream(speech, 2), state)
    )

    assert spoken == speech
    assert state.read_answer_owed is False


@pytest.mark.asyncio
@pytest.mark.parametrize("chunk_size", [1, 2, 3])
@pytest.mark.parametrize(
    ("result", "speech"),
    [
        (
            {
                "availability": "17:00, 17:15",
                "doctor_name": "Dr Rao",
                "date": "2026-08-28",
            },
            "Dr Rao is available at 2:30 PM.",
        ),
        (
            {"availability": "17:00, 17:15"},
            "2:30 PM is available. Five P.M. is also available.",
        ),
        (
            {
                "bookings": [
                    {
                        "patient_name": "Asha",
                        "doctor": "Dr Rao",
                        "date": "2026-08-28",
                        "time": "17:00",
                    }
                ]
            },
            "Asha, your appointment is at 2:30 PM.",
        ),
    ],
)
async def test_matching_name_cannot_authorize_an_invented_read_time(
    chunk_size,
    result,
    speech,
):
    state = SessionState(
        language="en",
        read_answer_owed=True,
        read_owed_utterance="Please check that.",
        read_result_evidence=_read_result_evidence(result, "en"),
    )

    spoken = await _collect_stream(
        _settle_read_answer_stream(_text_stream(speech, chunk_size), state)
    )

    assert spoken == ""
    assert state.read_answer_owed is True


@pytest.mark.asyncio
@pytest.mark.parametrize("speech", ["Your appointment is at 5 PM.", "Five P.M. is available."])
async def test_equivalent_numeric_or_spoken_time_settles_read_answer(speech):
    state = SessionState(
        language="en",
        read_answer_owed=True,
        read_owed_utterance="Is 5 PM available?",
        read_result_evidence=_read_result_evidence(
            {"appointment_time": "17:00"}, "en"
        ),
    )

    spoken = await _collect_stream(
        _settle_read_answer_stream(_text_stream(speech, 1), state)
    )

    assert spoken == speech
    assert state.read_answer_owed is False


@pytest.mark.asyncio
@pytest.mark.parametrize("chunk_size", [1, 2, 3])
@pytest.mark.parametrize(
    ("result", "speech"),
    [
        (
            {
                "doctor_name": "Dr Rao",
                "date": "2026-08-28",
                "appointment_time": "17:00",
            },
            "Dr Lakshmi is available on 29 August at 5 PM.",
        ),
        (
            {"your_token": 7, "now_serving": 3, "people_ahead": 4},
            "Your token is 12. Token 3 is being served.",
        ),
        (
            {"your_token": 7, "now_serving": 3, "people_ahead": 4},
            "Your token is twelve; there are four people ahead.",
        ),
        (
            {
                "bookings": [
                    {
                        "patient_name": "Usha",
                        "doctor": "Dr Rao",
                        "date": "2026-08-28",
                        "time": "17:00",
                    }
                ]
            },
            "Asha has the appointment at 5 PM.",
        ),
        (
            {
                "doctor": "Dr Rao",
                "date": "2026-08-28",
                "sitting_hours": "09:00-12:00 and 17:00-21:00",
            },
            "Dr Rao sits from 2:30 PM to 8 PM.",
        ),
        (
            {"doctor": "Dr Rao", "availability": "17:00, 17:15"},
            "Dr Rao time is two twenty P.M.",
        ),
        (
            {"doctor": "Dr Rao", "availability": "17:00, 17:15"},
            "The doctor time is twenty past two. Dr Rao is available.",
        ),
        (
            {
                "availability": "17:00, 17:15",
                "doctor_name": "Dr Rao",
                "date": "2026-08-28",
            },
            "Dr Rao is unavailable at 5 PM.",
        ),
        (
            {
                "availability": "17:00, 17:15",
                "doctor_name": "Dr Rao",
                "date": "2026-08-28",
            },
            "There are no openings at 5 PM.",
        ),
        (
            {"doctor_name": "Dr Rao", "date": "2026-08-28", "time": "17:00"},
            "Dr Rao is available tomorrow at 5 PM.",
        ),
        (
            {"doctor_name": "Dr Rao", "date": "2026-08-28", "time": "17:00"},
            "Dr Rao is available on Sunday at 5 PM.",
        ),
        (
            {"doctor_name": "Dr Rao", "date": "2026-08-28", "time": "17:00"},
            "Dr Rao is available on Aug 29 at 5 PM.",
        ),
        (
            {"doctor_name": "Dr Rao", "date": "2026-08-28", "time": "17:00"},
            "Dr Rao is available on 29th August at 5 PM.",
        ),
        (
            {"doctor_name": "Dr Rao", "date": "2026-08-28", "time": "17:00"},
            "Dr Rao is available on twenty ninth August at 5 PM.",
        ),
        (
            {"your_token": 42, "now_serving": 10, "people_ahead": 3, "doctor_name": "Dr Rao"},
            "Dr Rao has you; token number 43 is yours.",
        ),
        (
            {"your_token": 42, "now_serving": 10, "people_ahead": 3, "doctor_name": "Dr Rao"},
            "Dr Rao has you as queue number 43.",
        ),
        (
            {"your_token": 42, "now_serving": 10, "people_ahead": 3, "doctor_name": "Dr Rao"},
            "Your token is forty three with Dr Rao.",
        ),
        (
            {"your_token": 42, "now_serving": 10, "people_ahead": 3},
            "Your token is 42. Now serving number 11.",
        ),
        (
            {"your_token": 42, "now_serving": 10, "people_ahead": 3},
            "Your token is 42. They are serving 11 now.",
        ),
        (
            {"your_token": 42, "now_serving": 10, "people_ahead": 3},
            "Your token is 42. Four patients are before you.",
        ),
        (
            {"doctor_name": "Dr Rao", "time": "17:00"},
            "Dr Rao has you at quarter after two.",
        ),
        (
            {"doctor_name": "Dr Rao", "time": "17:00"},
            "Dr Rao has you at fourteen hundred hours.",
        ),
        (
            {"doctor_name": "Dr Rao", "time": "17:00"},
            "Dr Rao has you at noon.",
        ),
        (
            {"doctor_name": "Dr Rao", "time": "17:00"},
            "Dr Rao has you at half two.",
        ),
        (
            {
                "bookings": [{
                    "patient_name": "Usha",
                    "doctor": "Dr Rao",
                    "date": "2026-08-28",
                    "time": "17:00",
                }]
            },
            "Patient Asha has 5 PM.",
        ),
    ],
)
async def test_one_true_read_fact_cannot_launder_other_false_fields(
    chunk_size,
    result,
    speech,
):
    state = SessionState(
        language="en",
        read_answer_owed=True,
        read_owed_utterance="Please check that.",
        read_result_evidence=_read_result_evidence(result, "en"),
    )

    spoken = await _collect_stream(
        _settle_read_answer_stream(_text_stream(speech, chunk_size), state)
    )

    assert spoken == ""
    assert state.read_answer_owed is True


@pytest.mark.asyncio
@pytest.mark.parametrize("chunk_size", [1, 2, 3])
@pytest.mark.parametrize(
    ("question", "result", "incomplete_speech"),
    [
        (
            "What time is Dr Rao available on August 28?",
            {"doctor_name": "Dr Rao", "date": "2026-08-28", "availability": "17:00, 17:15"},
            "Dr Rao is available on 28 August.",
        ),
        (
            "What time is my appointment?",
            {
                "bookings": [{
                    "patient_name": "Usha",
                    "doctor": "Dr Rao",
                    "date": "2026-08-28",
                    "time": "17:00",
                }]
            },
            "Your appointment with Dr Rao was found.",
        ),
        (
            "How many patients are ahead of me?",
            {"your_token": 42, "now_serving": 10, "people_ahead": 3},
            "Your token is 42.",
        ),
        (
            "What token is being served now?",
            {"your_token": 42, "now_serving": 10, "people_ahead": 3},
            "Your token is 42.",
        ),
        (
            "What is my token number?",
            {"your_token": 42},
            "Your appointment was found.",
        ),
        (
            "What token is being served now?",
            {"now_serving": 42},
            "The queue was found.",
        ),
        (
            "How many patients are ahead of me?",
            {"people_ahead": 23},
            "The queue was found.",
        ),
    ],
)
async def test_owed_read_requires_the_fact_the_caller_asked_for(
    chunk_size,
    question,
    result,
    incomplete_speech,
):
    state = SessionState(
        language="en",
        read_answer_owed=True,
        read_owed_utterance=question,
        read_result_evidence=_read_result_evidence(result, "en"),
    )

    spoken = await _collect_stream(
        _settle_read_answer_stream(_text_stream(incomplete_speech, chunk_size), state)
    )

    assert spoken == ""
    assert state.read_answer_owed is True


@pytest.mark.asyncio
@pytest.mark.parametrize("chunk_size", [1, 2, 3])
@pytest.mark.parametrize(
    ("language", "question", "incomplete_speech"),
    [
        (
            "te",
            "డాక్టర్ రావు ఎప్పుడు అందుబాటులో ఉంటారు?",
            "డాక్టర్ Dr Rao గారు అందుబాటులో ఉన్నారు.",
        ),
        ("hi", "डॉक्टर राव कब उपलब्ध हैं?", "डॉक्टर Dr Rao उपलब्ध हैं।"),
        ("ta", "டாக்டர் ராவ் எப்போது கிடைப்பார்?", "மருத்துவர் Dr Rao இருக்கிறார்."),
        ("kn", "ಡಾಕ್ಟರ್ ರಾವ್ ಯಾವಾಗ ಲಭ್ಯ?", "ಡಾಕ್ಟರ್ Dr Rao ಲಭ್ಯವಿದ್ದಾರೆ."),
        ("ml", "ഡോക്ടർ റാവു എപ്പോൾ ലഭ്യമാണ്?", "ഡോക്ടർ Dr Rao ലഭ്യമാണ്."),
        ("mr", "डॉक्टर राव कधी उपलब्ध आहेत?", "डॉक्टर Dr Rao उपलब्ध आहेत."),
        ("bn", "ডাক্তার রাও কখন পাওয়া যাবেন?", "ডাক্তার Dr Rao আছেন।"),
    ],
)
async def test_native_when_question_cannot_settle_without_date_and_time(
    chunk_size,
    language,
    question,
    incomplete_speech,
):
    result = {
        "doctor_name": "Dr Rao",
        "date": "2026-08-28",
        "availability": "17:00, 17:15",
    }
    state = SessionState(
        language=language,
        read_answer_owed=True,
        read_owed_utterance=question,
        read_result_evidence=_read_result_evidence(result, language),
    )

    spoken = await _collect_stream(
        _settle_read_answer_stream(
            _text_stream(incomplete_speech, chunk_size),
            state,
        )
    )

    assert spoken == ""
    assert state.read_answer_owed is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("question", "result", "truthful_speech"),
    [
        ("What is my token number?", {"your_token": 42}, "Your token is forty two."),
        (
            "What token is being served now?",
            {"now_serving": 42},
            "Token forty two is now being served.",
        ),
        (
            "How many patients are ahead of me?",
            {"people_ahead": 23},
            "There are twenty three patients ahead.",
        ),
    ],
)
async def test_required_queue_facts_accept_equivalent_spoken_numbers(
    question,
    result,
    truthful_speech,
):
    state = SessionState(
        language="en",
        read_answer_owed=True,
        read_owed_utterance=question,
        read_result_evidence=_read_result_evidence(result, "en"),
    )

    spoken = await _collect_stream(
        _settle_read_answer_stream(_text_stream(truthful_speech, 1), state)
    )

    assert spoken == truthful_speech
    assert state.read_answer_owed is False


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["available", "unavailable"])
async def test_status_evidence_matches_whole_words_and_preserves_truth(status):
    speech = f"It is {status}."
    state = SessionState(
        language="en",
        read_answer_owed=True,
        read_owed_utterance="Is it available?",
        read_result_evidence=_read_result_evidence({"status": status}, "en"),
    )

    spoken = await _collect_stream(
        _settle_read_answer_stream(_text_stream(speech, 1), state)
    )

    assert spoken == speech
    assert state.read_answer_owed is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "speech",
    (
        "For Asha. Your appointment with Dr Rao on 28 August was cancelled by the clinic.",
        "For Asha. Your appointment with Dr Rao on 28 August at 5 PM is confirmed.",
    ),
)
async def test_verified_read_receipt_is_exact_and_one_use(speech):
    state = SessionState(language="en", verified_read_speech=speech)

    first = await _collect_stream(
        _guard_unverified_action_speech_stream(
            _text_stream(speech, 1),
            "en",
            verified_speech=speech,
            verified_state=state,
        )
    )
    replay = await _collect_stream(
        _guard_unverified_action_speech_stream(
            _text_stream(speech, 2),
            "en",
            verified_state=state,
        )
    )

    assert first == speech
    assert state.verified_read_speech is None
    assert replay == ""


@pytest.mark.asyncio
async def test_current_read_receipt_replaces_a_wrong_time_paraphrase():
    receipt = (
        "For Asha. Your appointment with Dr Rao on 28 August at 5 PM is confirmed."
    )
    wrong = (
        "For Asha. Your appointment with Dr Rao is on 28 August at 2:30 PM."
    )
    state = SessionState(language="en", verified_read_speech=receipt)

    spoken = await _collect_stream(
        _guard_unverified_action_speech_stream(
            _text_stream(wrong, 1),
            "en",
            verified_speech=receipt,
            verified_state=state,
        )
    )

    assert spoken == receipt
    assert state.verified_read_speech is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "false_speech",
    (
        "Dr Rao is available on 28 August.",
        "Dr Rao has appointments on 28 August.",
        "Dr Rao is seeing patients on 28 August.",
    ),
)
async def test_actual_false_availability_shape_blocks_positive_claims(false_speech):
    result = {
        "doctor": "Dr Rao",
        "date": "2026-08-28",
        "available": False,
        "instruction": "Dr Rao does not sit on 28 August.",
    }
    state = SessionState(
        language="en",
        read_answer_owed=True,
        read_owed_utterance="Is Dr Rao available on August 28?",
        read_result_evidence=_read_result_evidence(result, "en"),
    )

    spoken = await _collect_stream(
        _settle_read_answer_stream(_text_stream(false_speech, 1), state)
    )

    assert spoken == ""
    assert state.read_answer_owed is True


@pytest.mark.asyncio
async def test_actual_false_availability_shape_allows_truthful_negative():
    result = {"doctor": "Dr Rao", "date": "2026-08-28", "available": False}
    speech = "Dr Rao does not sit on 28 August."
    state = SessionState(
        language="en",
        read_answer_owed=True,
        read_owed_utterance="Is Dr Rao available on August 28?",
        read_result_evidence=_read_result_evidence(result, "en"),
    )

    spoken = await _collect_stream(
        _settle_read_answer_stream(_text_stream(speech, 2), state)
    )

    assert spoken == speech
    assert state.read_answer_owed is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("availability", "truthful"),
    (
        (
            "5:00 PM is occupied. NEAREST free times to their request: "
            "5:15 PM or 5:45 PM. All BOOKABLE APPOINTMENT STARTS: "
            "5:15 PM, 5:45 PM.",
            "5 PM is occupied. 5:15 PM and 5:45 PM are free.",
        ),
        (
            "5:00 PM is not a bookable appointment start in the published "
            "schedule; do NOT say it is already booked. NEAREST free times "
            "to their request: 5:15 PM or 5:45 PM.",
            "5 PM is not a bookable appointment start. 5:15 PM is free.",
        ),
        (
            "5:00 PM today has already passed. NEAREST free times to their "
            "request: 5:15 PM or 5:45 PM.",
            "5 PM has already passed. 5:15 PM is free.",
        ),
        (
            "Requested window is NOT free. There is no free start between "
            "5:00 PM and 5:30 PM. NEAREST free times to their request: "
            "5:45 PM or 6:15 PM.",
            "The 5 PM window is not free. 5:45 PM is free.",
        ),
    ),
)
async def test_negative_exact_time_never_becomes_an_available_time(
    availability, truthful
):
    evidence = _read_result_evidence({"availability": availability}, "en")
    false_state = SessionState(
        language="en",
        read_answer_owed=True,
        read_owed_utterance="Is 5 PM available?",
        read_result_evidence=evidence,
    )
    true_state = SessionState(
        language="en",
        read_answer_owed=True,
        read_owed_utterance="Is 5 PM available?",
        read_result_evidence=evidence,
    )

    false_spoken = await _collect_stream(
        _settle_read_answer_stream(
            _text_stream("5 PM is available.", 1), false_state
        )
    )
    true_spoken = await _collect_stream(
        _settle_read_answer_stream(_text_stream(truthful, 1), true_state)
    )

    assert false_spoken == ""
    assert false_state.read_answer_owed is True
    assert true_spoken == truthful
    assert true_state.read_answer_owed is False


@pytest.mark.asyncio
async def test_unpublished_time_cannot_be_called_occupied():
    availability = (
        "5:00 PM is not a bookable appointment start in the published schedule. "
        "NEAREST free times to their request: 5:15 PM or 5:45 PM."
    )
    state = SessionState(
        language="en",
        read_answer_owed=True,
        read_owed_utterance="Is 5 PM available?",
        read_result_evidence=_read_result_evidence(
            {"availability": availability}, "en"
        ),
    )

    spoken = await _collect_stream(
        _settle_read_answer_stream(
            _text_stream("5 PM is occupied. 5:15 PM is free.", 1), state
        )
    )

    assert spoken == ""
    assert state.read_answer_owed is True


@pytest.mark.asyncio
async def test_token_capacity_sitting_hours_are_not_bookable_clock_slots():
    availability = (
        "Doctor has 2 patients booked on 28 August. Published sitting sessions: "
        "05:00 PM to 09:00 PM. Capacity remains, but no token is reserved or "
        "assigned until the booking write succeeds."
    )
    state = SessionState(
        language="en",
        read_answer_owed=True,
        read_owed_utterance="Is 5 PM available?",
        read_result_evidence=_read_result_evidence(
            {"availability": availability}, "en"
        ),
    )

    spoken = await _collect_stream(
        _settle_read_answer_stream(
            _text_stream("5 PM is available.", 1), state
        )
    )

    assert spoken == ""
    assert state.read_answer_owed is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("availability", "truthful"),
    (
        (
            "SCHEDULE NOT PUBLISHED for Dr Rao on 28 August. Say only that the "
            "timing is not confirmed yet.",
            "Dr Rao's timing is not confirmed yet on 28 August.",
        ),
        (
            "Dr Rao is on leave on 28 August. Offer another date.",
            "Dr Rao is on leave on 28 August.",
        ),
        (
            "The clinic explicitly published no sessions for Dr Rao on "
            "28 August. Say the doctor is unavailable that date.",
            "Dr Rao is unavailable on 28 August.",
        ),
        (
            "Dr Rao has finished the final published session for today "
            "(9:00 PM). Ask for another date.",
            "Dr Rao has finished the final session for today.",
        ),
        (
            "28 August is in the past. Ask for a future date.",
            "28 August is in the past.",
        ),
        (
            "Doctor's schedule is not configured. Please call the clinic directly.",
            "The doctor's schedule is not configured.",
        ),
        ("Doctor not found.", "Doctor not found."),
    ),
)
async def test_terminal_availability_results_have_a_specific_truthful_path(
    availability, truthful
):
    state = SessionState(
        language="en",
        read_answer_owed=True,
        read_owed_utterance="Is the doctor available?",
        read_result_evidence=_read_result_evidence(
            {"availability": availability}, "en"
        ),
    )

    spoken = await _collect_stream(
        _settle_read_answer_stream(_text_stream(truthful, 1), state)
    )

    assert spoken == truthful
    assert state.read_answer_owed is False


@pytest.mark.asyncio
async def test_nested_next_available_date_is_the_only_valid_return_date():
    result = {
        "doctor": "Dr Rao",
        "date": "2026-08-28",
        "available": False,
        "next_available": {
            "date": "2026-09-02",
            "spoken_date": "02 September",
            "availability": "Bookable appointment starts: 17:00, 17:15",
            "leave_through": "2026-09-01",
        },
    }
    for speech, expected in (
        ("Dr Rao returns on 2 September and is bookable at 5 PM.", True),
        ("Dr Rao returns on 28 August.", False),
    ):
        state = SessionState(
            language="en",
            read_answer_owed=True,
            read_owed_utterance="When does Dr Rao return?",
            read_result_evidence=_read_result_evidence(result, "en"),
        )
        spoken = await _collect_stream(
            _settle_read_answer_stream(_text_stream(speech, 1), state)
        )
        assert bool(spoken) is expected
        assert state.read_answer_owed is not expected


@pytest.mark.asyncio
async def test_return_result_without_a_date_blocks_an_invented_date():
    result = {"doctor": "Dr Rao", "available": False}
    speech = "Dr Rao returns on 2 September."
    state = SessionState(
        language="en",
        read_answer_owed=True,
        read_owed_utterance="When does Dr Rao return?",
        read_result_evidence=_read_result_evidence(result, "en"),
    )

    spoken = await _collect_stream(
        _settle_read_answer_stream(_text_stream(speech, 1), state)
    )

    assert spoken == ""
    assert state.read_answer_owed is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("result", "question", "partial", "complete"),
    (
        (
            {
                "doctor": "Dr Rao",
                "date": "2026-08-28",
                "sitting_hours": (
                    "09:00 AM to 12:00 PM and 05:00 PM to 09:00 PM"
                ),
            },
            "What are all Dr Rao's hours on August 28?",
            "Dr Rao sits from 9 AM to 12 PM on 28 August.",
            (
                "Dr Rao sits from 9 AM to 12 PM and from 5 PM to 9 PM "
                "on 28 August."
            ),
        ),
        (
            {"availability": "16:45, 17:15, 17:45, 18:15"},
            "What are all available times?",
            "4:45 PM is available.",
            "4:45 PM, 5:15 PM, 5:45 PM, and 6:15 PM are available.",
        ),
    ),
)
async def test_all_times_question_requires_every_returned_time(
    result, question, partial, complete
):
    evidence = _read_result_evidence(result, "en")
    partial_state = SessionState(
        language="en",
        read_answer_owed=True,
        read_owed_utterance=question,
        read_result_evidence=evidence,
    )
    complete_state = SessionState(
        language="en",
        read_answer_owed=True,
        read_owed_utterance=question,
        read_result_evidence=evidence,
    )

    partial_spoken = await _collect_stream(
        _settle_read_answer_stream(_text_stream(partial, 2), partial_state)
    )
    complete_spoken = await _collect_stream(
        _settle_read_answer_stream(_text_stream(complete, 2), complete_state)
    )

    assert partial_spoken == ""
    assert partial_state.read_answer_owed is True
    assert complete_spoken == complete
    assert complete_state.read_answer_owed is False


@pytest.mark.asyncio
async def test_actual_nested_queue_shape_grounds_all_positions():
    result = {
        "found": True,
        "queue": [
            {
                "patient_name": "Asha",
                "doctor": "Dr Rao",
                "token_number": 7,
                "now_serving": 4,
                "patients_ahead": 2,
            }
        ],
    }
    speech = (
        "Your token is 7. Token 4 is now being served, with 2 patients ahead."
    )
    state = SessionState(
        language="en",
        read_answer_owed=True,
        read_owed_utterance=(
            "What is my token, what is now serving, and how many are ahead?"
        ),
        read_result_evidence=_read_result_evidence(result, "en"),
    )

    spoken = await _collect_stream(
        _settle_read_answer_stream(_text_stream(speech, 1), state)
    )

    assert spoken == speech
    assert state.read_answer_owed is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("now_serving", "speech", "allowed"),
    (
        (None, "Your token is 7.", False),
        (None, "Your token is 7. The queue is running.", False),
        (None, "Your token is 7. The queue has not started yet.", True),
        (4, "Your token is 7. The queue has not started yet.", False),
        (4, "Your token is 7. Token 4 is now being served.", True),
    ),
)
async def test_queue_started_question_requires_truthful_queue_state(
    now_serving, speech, allowed
):
    result = {
        "found": True,
        "queue": [
            {
                "token_number": 7,
                "now_serving": now_serving,
                "patients_ahead": 2,
            }
        ],
    }
    state = SessionState(
        language="en",
        read_answer_owed=True,
        read_owed_utterance="Has the queue started yet?",
        read_result_evidence=_read_result_evidence(result, "en"),
    )

    spoken = await _collect_stream(
        _settle_read_answer_stream(_text_stream(speech, 1), state)
    )

    assert bool(spoken) is allowed
    assert state.read_answer_owed is not allowed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "unsafe",
    (
        "Your token is 7. It should take about 15 minutes.",
        "Your token is 7. You should be called in ten minutes.",
        "Your token is 7. You are next in line.",
    ),
)
async def test_queue_status_never_invents_wait_duration_or_rank(unsafe):
    result = {
        "found": True,
        "queue": [
            {"token_number": 7, "now_serving": 4, "patients_ahead": 2}
        ],
    }
    state = SessionState(
        language="en",
        read_answer_owed=True,
        read_owed_utterance="When will my turn come?",
        read_result_evidence=_read_result_evidence(result, "en"),
    )

    spoken = await _collect_stream(
        _settle_read_answer_stream(_text_stream(unsafe, 1), state)
    )

    assert spoken == ""
    assert state.read_answer_owed is True


@pytest.mark.asyncio
@pytest.mark.parametrize("chunk_size", (1, 2, 3))
@pytest.mark.parametrize(
    ("speech", "allowed"),
    (
        (
            "For Asha, token number 7; they are now serving 4 and 2 patients "
            "are ahead. For Bina, token number 9; they are now serving 6 and "
            "3 patients are ahead.",
            True,
        ),
        (
            "For Asha, token number 9; they are now serving 6 and 3 patients "
            "are ahead. For Bina, token number 7; they are now serving 4 and "
            "2 patients are ahead.",
            False,
        ),
        (
            "Token number 9 is for Asha, with 3 patients ahead. "
            "Token number 7 is for Bina, with 2 patients ahead.",
            False,
        ),
        (
            "For Asha, token number 7; they are now serving 4 and 2 patients "
            "are ahead.",
            False,
        ),
    ),
)
async def test_all_queue_statuses_keep_facts_on_their_own_entry(
    chunk_size, speech, allowed
):
    result = {
        "found": True,
        "queue": [
            {
                "patient_name": "Asha",
                "doctor": "Dr Rao",
                "token_number": 7,
                "now_serving": 4,
                "patients_ahead": 2,
            },
            {
                "patient_name": "Bina",
                "doctor": "Dr Shah",
                "token_number": 9,
                "now_serving": 6,
                "patients_ahead": 3,
            },
        ],
    }
    state = SessionState(
        language="en",
        read_answer_owed=True,
        read_owed_utterance=(
            "What are all the token queue statuses for Asha and Bina?"
        ),
        read_result_evidence=_read_result_evidence(result, "en"),
    )

    spoken = await _collect_stream(
        _settle_read_answer_stream(_text_stream(speech, chunk_size), state)
    )

    assert bool(spoken) is allowed
    assert state.read_answer_owed is not allowed


@pytest.mark.asyncio
@pytest.mark.parametrize("chunk_size", (1, 2, 3))
@pytest.mark.parametrize(
    ("speech", "allowed"),
    (
        ("They are now serving 4 and 2 patients are ahead.", True),
        ("They are now serving 4. You are third in line.", True),
        ("They are now serving 4. You are ninth in line.", False),
        ("They are now serving 4. You are number 10 in line.", False),
        ("They are now serving 4. There are dozens ahead of you.", False),
    ),
)
async def test_queue_rank_and_ahead_quantity_must_match_the_live_result(
    chunk_size, speech, allowed
):
    result = {
        "found": True,
        "queue": [
            {
                "token_number": 7,
                "now_serving": 4,
                "patients_ahead": 2,
            }
        ],
    }
    state = SessionState(
        language="en",
        read_answer_owed=True,
        read_owed_utterance="When will my turn come?",
        read_result_evidence=_read_result_evidence(result, "en"),
    )

    spoken = await _collect_stream(
        _settle_read_answer_stream(_text_stream(speech, chunk_size), state)
    )

    assert bool(spoken) is allowed
    assert state.read_answer_owed is not allowed


@pytest.mark.asyncio
@pytest.mark.parametrize("chunk_size", (1, 2, 3))
@pytest.mark.parametrize(
    "question",
    ("Cancel my appointment.", "Reschedule my appointment."),
)
async def test_empty_booking_lookup_exactly_settles_cancel_or_reschedule_read(
    chunk_size, question
):
    speech = build_no_booking_found_text("en")
    evidence = _read_result_evidence({"bookings": []}, "en")
    state = SessionState(
        language="en",
        read_answer_owed=True,
        read_owed_utterance=question,
        read_result_evidence=evidence,
    )

    spoken = await _collect_stream(
        _settle_read_answer_stream(_text_stream(speech, chunk_size), state)
    )

    assert any(group.startswith("bookings_empty\x1e") for group in evidence)
    assert spoken == speech
    assert state.read_answer_owed is False


@pytest.mark.asyncio
async def test_empty_booking_lookup_rejects_a_preface_before_the_exact_result():
    result = {"bookings": []}
    speech = "I checked. " + build_no_booking_found_text("en")
    state = SessionState(
        language="en",
        read_answer_owed=True,
        read_owed_utterance="Cancel my appointment.",
        read_result_evidence=_read_result_evidence(result, "en"),
    )

    spoken = await _collect_stream(
        _settle_read_answer_stream(_text_stream(speech, 2), state)
    )

    assert spoken == ""
    assert state.read_answer_owed is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("result", "truthful_speech"),
    [
        (
            {
                "out_of_scope": True,
                "confidence": "none",
                "treated_specialties": ["Dermatology", "Dentistry"],
            },
            "This clinic treats Dermatology and Dentistry, not this problem.",
        ),
        (
            {"found": False, "reason": "no token-queue booking today"},
            "There is no token-queue booking today.",
        ),
        (
            {"availability": "No slots available."},
            "No slots available.",
        ),
    ],
)
async def test_structured_negative_read_results_have_a_truthful_speech_path(
    result,
    truthful_speech,
):
    evidence = _read_result_evidence(result, "en")
    state = SessionState(
        language="en",
        read_answer_owed=True,
        read_owed_utterance="Can you check that?",
        read_result_evidence=evidence,
    )

    spoken = await _collect_stream(
        _settle_read_answer_stream(
            _text_stream(truthful_speech, 3),
            state,
        )
    )

    assert evidence, "a successful structured negative read needs safe evidence"
    assert spoken == truthful_speech
    assert state.read_answer_owed is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("result", "speech", "allowed"),
    (
        (
            {
                "doctor_name": "Dr Rao",
                "specialization": "Dermatology",
            },
            "Dr Rao is a Dermatology specialist.",
            True,
        ),
        (
            {
                "doctor_name": "Dr Rao",
                "specialization": "Dermatology",
            },
            "Dr Rao is a cardiologist.",
            False,
        ),
        (
            {
                "out_of_scope": True,
                "treated_specialties": ["Dermatology", "Dentistry"],
            },
            "This clinic treats Dermatology and Cardiology, not this problem.",
            False,
        ),
    ),
)
async def test_route_read_never_authorizes_an_unsupported_specialty(
    result, speech, allowed
):
    state = SessionState(
        language="en",
        read_answer_owed=True,
        read_owed_utterance="Which doctor treats this problem?",
        read_result_evidence=_read_result_evidence(result, "en"),
    )

    spoken = await _collect_stream(
        _settle_read_answer_stream(_text_stream(speech, 2), state)
    )

    assert bool(spoken) is allowed
    assert state.read_answer_owed is not allowed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("speech", "allowed"),
    (
        (
            "Dr Rao specializes in Dermatology and Dr Shah specializes in "
            "Dentistry.",
            True,
        ),
        ("Dr Rao specializes in Dermatology.", False),
        (
            "Dr Rao specializes in Dentistry and Dr Shah specializes in "
            "Dermatology.",
            False,
        ),
        (
            "Dr Rao specializes in Dermatology and General Medicine. "
            "Dr Shah specializes in General Medicine.",
            False,
        ),
    ),
)
async def test_route_read_requires_every_candidate_with_its_specialty(
    speech, allowed
):
    result = {
        "candidates": [
            {
                "doctor_name": "Dr Rao",
                "specialization": "Dermatology",
            },
            {
                "doctor_name": "Dr Shah",
                "specialization": "Dentistry",
            },
        ],
        "confidence": "high",
    }
    state = SessionState(
        language="en",
        read_answer_owed=True,
        read_owed_utterance="Which doctor treats this problem?",
        read_result_evidence=_read_result_evidence(result, "en"),
    )

    spoken = await _collect_stream(
        _settle_read_answer_stream(_text_stream(speech, 3), state)
    )

    assert bool(spoken) is allowed
    assert state.read_answer_owed is not allowed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("speech", "allowed"),
    (
        ("Do you mean a tooth problem or a work problem?", True),
        ("Is this about your tooth or your job?", False),
        ("Okay. Do you mean a tooth problem or a work problem?", False),
    ),
)
async def test_route_read_requires_the_exact_returned_clarification(
    speech, allowed
):
    result = {
        "needs_clarification": True,
        "confidence": "low",
        "clarification": "Do you mean a tooth problem or a work problem?",
    }
    state = SessionState(
        language="en",
        read_answer_owed=True,
        read_owed_utterance="I have a work problem.",
        read_result_evidence=_read_result_evidence(result, "en"),
    )

    spoken = await _collect_stream(
        _settle_read_answer_stream(_text_stream(speech, 1), state)
    )

    assert bool(spoken) is allowed
    assert state.read_answer_owed is not allowed


@pytest.mark.asyncio
@pytest.mark.parametrize("chunk_size", (1, 3))
@pytest.mark.parametrize(
    ("speech", "allowed"),
    (
        (
            "Asha is booked with Dr Rao on August 28 at 5 PM. "
            "Bina is booked with Dr Shah on August 29 at 6 PM.",
            True,
        ),
        (
            "Asha is booked with Dr Shah on August 29 at 6 PM. "
            "Bina is booked with Dr Rao on August 28 at 5 PM.",
            False,
        ),
        (
            "Asha is booked with Dr Rao on August 28 at 6 PM. "
            "Bina is booked with Dr Shah on August 29 at 5 PM.",
            False,
        ),
        (
            "The 6 PM appointment is under Asha. "
            "The 5 PM appointment is under Bina.",
            False,
        ),
        (
            "Asha is booked with Dr Rao on August 28 at 5 PM.",
            False,
        ),
    ),
)
async def test_multi_booking_read_keeps_every_field_on_its_own_record(
    chunk_size, speech, allowed
):
    result = {
        "bookings": [
            {
                "patient_name": "Asha",
                "doctor": "Dr Rao",
                "date": "2026-08-28",
                "time": "17:00",
            },
            {
                "patient_name": "Bina",
                "doctor": "Dr Shah",
                "date": "2026-08-29",
                "time": "18:00",
            },
        ]
    }
    state = SessionState(
        language="en",
        read_answer_owed=True,
        read_owed_utterance="What are all my bookings?",
        read_result_evidence=_read_result_evidence(result, "en"),
    )

    spoken = await _collect_stream(
        _settle_read_answer_stream(_text_stream(speech, chunk_size), state)
    )

    assert bool(spoken) is allowed
    assert state.read_answer_owed is not allowed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("question", "result", "speech"),
    (
        (
            "What is my appointment?",
            {
                "bookings": [
                    {
                        "patient_name": "Asha",
                        "doctor": "Dr Rao",
                        "date": "2026-08-28",
                        "time": "17:00",
                    }
                ]
            },
            "The appointment under Asha is with Dr Rao on 28 August at 5 PM. "
            "It is also under Bina.",
        ),
        (
            "What is my appointment?",
            {
                "bookings": [
                    {
                        "patient_name": "Asha",
                        "doctor": "Dr Rao",
                        "date": "2026-08-28",
                        "time": "17:00",
                    }
                ]
            },
            "The appointment under Asha is with Dr Rao on 28 August at 5 PM. "
            "Dr Patel is also listed as the doctor.",
        ),
        (
            "What is my appointment?",
            {
                "bookings": [
                    {
                        "patient_name": "Asha",
                        "doctor": "Dr Rao",
                        "date": "2026-08-28",
                        "time": "17:00",
                    }
                ]
            },
            "The appointment under Asha is with Dr Rao on 28 August at 5 PM. "
            "It is also on 30 August.",
        ),
        (
            "Which doctor treats skin problems?",
            {"doctor_name": "Dr Rao", "specialization": "Dermatology"},
            "Dr Rao is a dermatologist. Dr Patel is also a dermatologist.",
        ),
        (
            "Who is available on 28 August?",
            {
                "doctor": "Dr Rao",
                "date": "2026-08-28",
                "available": True,
                "availability": "BOOKABLE APPOINTMENT STARTS: 5:15 PM.",
            },
            "Dr Rao is available on 28 August at 5:15 PM. "
            "Dr Patel is also available then.",
        ),
    ),
)
async def test_one_true_tuple_cannot_launder_an_extra_named_entity(
    question, result, speech
):
    state = SessionState(
        language="en",
        read_answer_owed=True,
        read_owed_utterance=question,
        read_result_evidence=_read_result_evidence(result, "en"),
    )

    spoken = await _collect_stream(
        _settle_read_answer_stream(_text_stream(speech, 2), state)
    )

    assert spoken == ""
    assert state.read_answer_owed is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("speech", "allowed"),
    (
        ("We treat Dermatology and Dentistry.", True),
        ("We treat Dermatology.", False),
    ),
)
async def test_specialty_list_query_requires_every_returned_specialty(
    speech, allowed
):
    state = SessionState(
        language="en",
        read_answer_owed=True,
        read_owed_utterance="Which specialties do you treat?",
        read_result_evidence=_read_result_evidence(
            {"treated_specialties": ["Dermatology", "Dentistry"]}, "en"
        ),
    )

    spoken = await _collect_stream(
        _settle_read_answer_stream(_text_stream(speech, 3), state)
    )

    assert bool(spoken) is allowed
    assert state.read_answer_owed is not allowed


@pytest.mark.asyncio
async def test_real_availability_backend_failure_settles_filler_with_direct_speech(
    monkeypatch,
):
    entered = asyncio.Event()
    release = asyncio.Event()
    session = _ReadSession()
    state = SessionState(
        language="en",
        branch_id=uuid4(),
        last_user_utterance="Is 5 PM available tomorrow?",
    )
    agent = _agent(state)
    doctor_id = uuid4()
    agent._resolve_doctor_id = AsyncMock(return_value=doctor_id)

    async def broken_backend(**_kwargs):
        entered.set()
        await release.wait()
        raise RuntimeError("offline database failure")

    monkeypatch.setattr(agent_mod, "AgentSession", _ReadSession)
    monkeypatch.setattr(agent_mod, "check_availability", broken_backend)
    context = SimpleNamespace(session=session)
    task = asyncio.create_task(
        agent.check_availability(
            context,
            doctor_id=str(doctor_id),
            booking_date="2026-08-22",
            query_start="17:00",
        )
    )

    await entered.wait()
    assert state.read_in_flight_count == 1
    assert state.read_owed_utterance == "Is 5 PM available tomorrow?"
    assert [text for text, _ in session.said] == [
        "One moment, please. Let me check that."
    ]

    release.set()
    with pytest.raises(StopResponse):
        await task

    assert [text for text, _ in session.said] == [
        "One moment, please. Let me check that.",
        build_read_failure_text("en"),
    ]
    assert state.read_in_flight_count == 0
    assert state.read_owed_utterance is None


@pytest.mark.asyncio
async def test_hung_read_times_out_and_settles_the_wait_filler(monkeypatch):
    session = _ReadSession()
    state = SessionState(
        language="en",
        last_user_utterance="When is Dr Rao free tomorrow?",
    )
    owner = SimpleNamespace(_state=state, _lang_code="en")
    context = SimpleNamespace(session=session)
    never = asyncio.Event()

    monkeypatch.setattr(agent_mod, "AgentSession", _ReadSession)
    monkeypatch.setattr(agent_mod, "_READ_TOOL_TIMEOUT_SECONDS", 0.01)

    @_tracks_read
    async def hung_read(_owner, _context):
        _context.session.say("One moment, please. Let me check that.")
        await never.wait()

    with pytest.raises(StopResponse):
        await asyncio.wait_for(hung_read(owner, context), timeout=0.5)

    assert [text for text, _ in session.said] == [
        "One moment, please. Let me check that.",
        build_read_failure_text("en"),
    ]
    assert state.read_in_flight_count == 0
    assert state.read_owed_utterance is None


@pytest.mark.asyncio
async def test_final_speech_guards_release_first_safe_sentence_before_source_eof():
    first_sent = asyncio.Event()
    release = asyncio.Event()
    state = SessionState(language="en")

    async def delayed_source():
        first_sent.set()
        yield "The clinic opens at 9."
        await release.wait()
        yield " It closes at 6."

    guarded = _guard_output_language_stream(delayed_source(), "en")
    guarded = _guard_unbacked_checking_speech_stream(guarded, "en", state)
    guarded = _guard_unverified_action_speech_stream(
        guarded, "en", verified_state=state
    )
    iterator = guarded.__aiter__()

    first = await asyncio.wait_for(anext(iterator), timeout=0.2)
    assert first == "The clinic opens at 9."
    assert first_sent.is_set()

    release.set()
    rest = [part async for part in iterator]
    assert "".join([first, *rest]) == "The clinic opens at 9. It closes at 6."


@pytest.mark.asyncio
async def test_hello_and_repeated_question_cannot_supersede_owed_read_answer():
    entered = asyncio.Event()
    release = asyncio.Event()
    state = SessionState(
        language="en",
        last_user_utterance="When is my appointment?",
    )
    session = SimpleNamespace(agent_state="thinking", interrupt=Mock())
    fake = SimpleNamespace(
        _state=state,
        _lang_code="en",
        _message_text=VachanamAgent._message_text,
        _consecutive_hellos=0,
        session=session,
    )

    @_tracks_read
    async def delayed_lookup(_owner, _context):
        entered.set()
        await release.wait()
        return "Your verified appointment is at 5 PM."

    task = asyncio.create_task(delayed_lookup(fake, SimpleNamespace(session=object())))
    await entered.wait()

    for probe in ("hello", "When is my appointment?"):
        with pytest.raises(StopResponse):
            await VachanamAgent.on_user_turn_completed(
                fake, SimpleNamespace(items=[]), _message(probe)
            )

    session.interrupt.assert_not_called()
    assert fake._consecutive_hellos == 0
    assert not task.cancelled()
    assert state.read_owed_utterance == "When is my appointment?"

    release.set()
    assert await task == "Your verified appointment is at 5 PM."
    assert state.read_in_flight_count == 0


@pytest.mark.asyncio
async def test_probe_cannot_supersede_completed_read_before_answer_is_spoken():
    state = SessionState(
        language="en",
        last_user_utterance="When is my appointment?",
        read_answer_owed=True,
        read_owed_utterance="When is my appointment?",
        read_result_evidence=("time:17:00",),
    )
    session = SimpleNamespace(agent_state="thinking", interrupt=Mock())
    fake = SimpleNamespace(
        _state=state,
        _lang_code="en",
        _message_text=VachanamAgent._message_text,
        _consecutive_hellos=0,
        session=session,
    )

    for probe in ("hello", "When is my appointment?"):
        with pytest.raises(StopResponse):
            await VachanamAgent.on_user_turn_completed(
                fake, SimpleNamespace(items=[]), _message(probe)
            )

    session.interrupt.assert_not_called()
    assert state.read_answer_owed is True
    assert state.read_result_evidence == ("time:17:00",)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("caller", "model_output", "expected_intent"),
    (
        (
            "When is my appointment?",
            "Your appointment is at 2:30 PM.",
            "booking",
        ),
        (
            "Do I have a confirmed appointment?",
            "Yes, your appointment is confirmed.",
            "booking",
        ),
        (
            "Is Dr Rao available tomorrow?",
            "Dr Rao is available tomorrow at 5 PM.",
            "availability",
        ),
        (
            "What is Dr Rao's schedule?",
            "Dr Rao's schedule is 9 AM to 1 PM.",
            "availability",
        ),
        (
            "What token is serving now?",
            "Token 5 is serving now.",
            "queue",
        ),
    ),
)
async def test_callback_latches_mutable_read_before_model_tool_omission(
    caller,
    model_output,
    expected_intent,
):
    state = SessionState(language="en", preferred_language="en")
    session = SimpleNamespace(
        userdata={},
        agent_state="listening",
        interrupt=Mock(),
        say=AsyncMock(),
    )
    agent = _agent(state, session=session)

    await agent.on_user_turn_completed(ChatContext.empty(), _message(caller))

    assert state.mutable_read_intent == expected_intent
    assert state.mutable_read_utterance == caller
    spoken = await _collect_stream(
        _settle_read_answer_stream(_text_stream(model_output, 1), state)
    )
    assert spoken == build_read_failure_text("en")
    assert state.mutable_read_intent is None


@pytest.mark.asyncio
async def test_pre_read_latch_allows_identity_clarification_without_tool_result():
    state = SessionState(language="en", preferred_language="en")
    session = SimpleNamespace(
        userdata={},
        agent_state="listening",
        interrupt=Mock(),
        say=AsyncMock(),
    )
    agent = _agent(state, session=session)
    await agent.on_user_turn_completed(
        ChatContext.empty(), _message("When is my appointment?")
    )
    assert state.mutable_read_intent == "booking"
    assert state.read_answer_owed is False

    clarification = "Please tell me the patient's name."
    spoken = await _production_speech_boundary(
        clarification, state, chunk_size=2
    )

    assert spoken == clarification
    assert state.mutable_read_intent == "booking"

    await agent.on_user_turn_completed(ChatContext.empty(), _message("Vinay"))
    assert state.mutable_read_intent == "booking"
    fabricated = "Your appointment is at 2:30 PM."
    spoken = await _production_speech_boundary(fabricated, state, chunk_size=2)
    assert spoken == build_read_failure_text("en")
    assert state.mutable_read_intent is None


@pytest.mark.asyncio
async def test_wrong_read_tool_cannot_launder_existing_booking_claim():
    state = SessionState(
        language="en",
        mutable_read_intent="booking",
        mutable_read_utterance="When is my appointment?",
        last_user_utterance="When is my appointment?",
    )
    agent = _agent(state)

    @_tracks_read
    async def check_availability(_owner, _context):
        return {"slots": [{"time": "17:00", "available": True}]}

    result = await check_availability(
        agent, SimpleNamespace(session=object())
    )

    assert result["slots"][0]["time"] == "17:00"
    assert state.mutable_read_intent == "booking"
    assert state.read_answer_owed is False
    assert state.read_result_evidence == ()
    spoken = await _production_speech_boundary(
        "Your appointment is at 5 PM.", state
    )
    assert spoken == build_read_failure_text("en")


@pytest.mark.asyncio
async def test_matching_read_tool_settles_the_bound_mutable_intent():
    state = SessionState(
        language="en",
        mutable_read_intent="booking",
        mutable_read_utterance="When is my appointment?",
        last_user_utterance="When is my appointment?",
    )
    agent = _agent(state)

    @_tracks_read
    async def find_my_bookings(_owner, _context):
        return {
            "bookings": [
                {
                    "doctor": "Dr Rao",
                    "date": "2026-08-28",
                    "time": "17:00",
                }
            ]
        }

    await find_my_bookings(agent, SimpleNamespace(session=object()))

    assert state.mutable_read_intent is None
    assert state.read_answer_owed is True
    spoken = await _production_speech_boundary(
        "Your appointment with Dr Rao is at 5 PM on 28 August.", state
    )
    assert spoken == "Your appointment with Dr Rao is at 5 PM on 28 August."


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "superseding_turn",
    ("Never mind.", "Please book me tomorrow at 5 PM."),
)
async def test_mutable_read_latch_clears_on_explicit_abandonment_or_new_action(
    superseding_turn,
):
    state = SessionState(language="en", preferred_language="en")
    session = SimpleNamespace(
        userdata={},
        agent_state="listening",
        interrupt=Mock(),
        say=AsyncMock(),
    )
    agent = _agent(state, session=session)
    await agent.on_user_turn_completed(
        ChatContext.empty(), _message("When is my appointment?")
    )
    assert state.mutable_read_intent == "booking"

    await agent.on_user_turn_completed(
        ChatContext.empty(), _message(superseding_turn)
    )

    assert state.mutable_read_intent is None


@pytest.mark.asyncio
async def test_booking_request_and_confirmation_question_do_not_arm_read_latch():
    state = SessionState(language="en", preferred_language="en")
    session = SimpleNamespace(
        userdata={},
        agent_state="listening",
        interrupt=Mock(),
        say=AsyncMock(),
    )
    agent = _agent(state, session=session)
    await agent.on_user_turn_completed(
        ChatContext.empty(), _message("Book me tomorrow at 5 PM")
    )

    assert state.mutable_read_intent is None
    question = "Shall I book your appointment tomorrow at 5 PM?"
    spoken = await _collect_stream(
        _settle_read_answer_stream(_text_stream(question, 1), state)
    )
    assert spoken == question


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "clarification",
    (
        "I have to ask for the patient's name.",
        "I need to confirm your name before booking.",
        "I should confirm whether five works for you.",
        "The patient said she has chest pain.",
    ),
)
async def test_full_speech_chain_preserves_patient_facing_clarifications(
    clarification,
):
    state = SessionState(language="en")
    assert await _production_speech_boundary(
        clarification, state, chunk_size=1
    ) == clarification


@pytest.mark.asyncio
async def test_internal_only_model_reply_recovers_instead_of_silence():
    state = SessionState(language="en")
    trace = "I need to use check_availability with booking_date."
    spoken = await _production_speech_boundary(trace, state, chunk_size=1)
    assert spoken == _safe_output_recovery("en")
    assert spoken.strip()
    assert "check_availability" not in spoken


@pytest.mark.asyncio
async def test_wife_correction_is_not_mistaken_for_a_probe_during_slow_read():
    entered = asyncio.Event()
    release = asyncio.Event()
    session = SimpleNamespace(
        userdata={},
        agent_state="thinking",
        interrupt=Mock(),
        say=AsyncMock(),
    )
    state = SessionState(
        language="en",
        preferred_language="en",
        last_user_utterance="Is the 5 PM appointment for me?",
    )
    agent = _agent(state, session=session)

    @_tracks_read
    async def delayed_read(_owner, _context):
        entered.set()
        await release.wait()
        return "stale answer"

    task = asyncio.create_task(delayed_read(agent, SimpleNamespace(session=object())))
    await entered.wait()

    correction = "No, this is for my wife, not me."
    await agent.on_user_turn_completed(ChatContext.empty(), _message(correction))

    assert state.last_user_utterance == correction
    assert state.read_owed_utterance == "Is the 5 PM appointment for me?"
    assert state.read_in_flight_count == 1
    assert not task.cancelled()
    session.interrupt.assert_called_once_with()
    session.say.assert_not_awaited()

    release.set()
    assert await task == "stale answer"
    assert state.read_in_flight_count == 0


@pytest.mark.asyncio
async def test_production_watchdog_never_line_checks_while_read_answer_is_owed():
    entered = asyncio.Event()
    release = asyncio.Event()
    state = SessionState(
        language="en",
        last_user_utterance="Please check the doctor's schedule.",
    )
    owner = SimpleNamespace(_state=state, _lang_code="en")

    @_tracks_read
    async def delayed_read(_owner, _context):
        entered.set()
        await release.wait()
        return "verified schedule"

    read_task = asyncio.create_task(
        delayed_read(owner, SimpleNamespace(session=object()))
    )
    await entered.wait()

    ticks = _TickAsyncio()
    silence = {"last_user": 0.0, "prompts": 2, "linecheck": False}
    session = _WatchSession()
    watchdog = asyncio.create_task(
        _bound_watchdog(
            ticks=ticks,
            silence=silence,
            session=session,
            state=state,
        )()
    )

    ticks.tick()
    await _eventually(
        lambda: silence["last_user"] == 11.0 and silence["prompts"] == 0
    )
    assert session.said == []

    release.set()
    assert await read_task == "verified schedule"
    assert state.read_answer_owed is True
    assert state.read_owed_utterance == "Please check the doctor's schedule."

    silence["last_user"] = 0.0
    ticks.tick()
    await _eventually(lambda: silence["last_user"] == 11.0 or bool(session.said))
    assert silence["last_user"] == 11.0
    assert silence["prompts"] == 0
    assert session.said == []

    watchdog.cancel()
    with suppress(asyncio.CancelledError):
        await watchdog

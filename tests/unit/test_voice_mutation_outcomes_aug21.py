"""Runtime regressions for grounded voice mutation outcomes.

These tests use only fake sessions and database objects.  They exercise the
same wrapper and final speech-boundary code used by the LiveKit agent without
touching Redis, Calendar, a real database, or the network.
"""

from __future__ import annotations

import asyncio
from datetime import date, time, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest
from livekit.agents import StopResponse, ToolError
from livekit.agents.llm import ChatContext

from agent.livekit_minimal import agent as agent_mod
from agent.livekit_minimal.agent import (
    VachanamAgent,
    _guard_output_language_stream,
    _guard_unverified_action_speech_stream,
)
from agent.livekit_minimal.confirm_speech import (
    build_action_continue_text,
    build_booking_confirmation_question,
    build_booking_failure_text,
    build_booking_unavailable_text,
    build_cancellation_confirmation_question,
    build_clinic_message_ack,
    build_clinic_question_ack,
    build_confirm_text,
    build_mutation_failure_text,
    build_relay_content_request_text,
    build_transfer_failure_text,
)
from agent.session_state import SessionState


LANGUAGES = ("en", "te", "hi", "ta", "kn", "ml", "mr", "bn")

CONFIRMATION_QUESTIONS = {
    "en": "Shall I book your appointment at 5 PM?",
    "te": "మీ అపాయింట్‌మెంట్‌ను 5 గంటలకు బుక్ చేయనా?",
    "hi": "क्या मैं आपकी अपॉइंटमेंट 5 बजे बुक कर दूँ?",
    "ta": "உங்கள் அப்பாயின்ட்மென்ட்டை 5 மணிக்கு புக் செய்யவா?",
    "kn": "ನಿಮ್ಮ ಅಪಾಯಿಂಟ್ಮೆಂಟ್ ಅನ್ನು 5 ಗಂಟೆಗೆ ಬುಕ್ ಮಾಡಲಾ?",
    "ml": "നിങ്ങളുടെ അപ്പോയിന്റ്മെന്റ് 5 മണിക്ക് ബുക്ക് ചെയ്യട്ടേ?",
    "mr": "मी तुमची अपॉइंटमेंट 5 वाजता बुक करू का?",
    "bn": "আমি কি আপনার অ্যাপয়েন্টমেন্ট ৫টায় বুক করব?",
}

SEMANTIC_BOOKING_CLAIMS = {
    "en": "I fixed your time for 5 PM.",
    "te": "మీకు 5 గంటలకు టైం ఫిక్స్ చేశాను అండి.",
    "hi": "आपका समय 5 बजे तय कर दिया है।",
    "ta": "உங்களுக்கு 5 மணிக்கு நேரம் வைத்துவிட்டேன்.",
    "kn": "ನಿಮಗೆ 5 ಗಂಟೆಗೆ ಸಮಯ ನಿಗದಿ ಮಾಡಿದ್ದೇನೆ.",
    "ml": "നിങ്ങൾക്ക് 5 മണിക്ക് സമയം ഉറപ്പാക്കി.",
    "mr": "तुमची वेळ 5 वाजता ठरवली आहे.",
    "bn": "আপনার সময় ৫টায় ঠিক করে দিয়েছি।",
}

ENGLISH_ACTION_CLAIMS = (
    ("booking", "I made your appointment for 5:00 PM."),
    ("booking", "You're on the calendar for 5:00 PM."),
    ("booking", "Done, you are set for 5:00 PM."),
    ("message", "The clinic has your message."),
    ("message", "I passed your message to the clinic."),
    ("cancel", "I removed your appointment."),
    ("reschedule", "I changed your appointment to 6:00 PM."),
    ("booking", "I've put you down for 5 PM."),
    ("booking", "Your visit is arranged for 5 PM."),
    ("booking", "Your spot is secured for 5 PM."),
    ("booking", "Five PM is yours."),
    ("booking", "You're in for 5 PM."),
    ("booking", "I added you to Dr Rao's list."),
    ("booking", "Your appointment is locked in for 5 PM."),
    ("message", "I left a note for the clinic."),
    ("message", "They'll see your note."),
    ("message", "It's with the clinic now."),
    ("message", "I've added it to the clinic inbox."),
    ("question", "I put your question in their queue."),
    ("question", "The clinic will review your question."),
    ("cancel", "That appointment is gone."),
    ("cancel", "I've taken it off."),
    ("reschedule", "You're now down for 6 PM."),
    ("reschedule", "The new time is locked in at 6 PM."),
    ("booking", "Consider your 5 PM appointment taken care of."),
    ("booking", "The doctor will see you at 5 PM."),
    ("booking", "Your name is on the 5 PM schedule."),
    ("booking", "I have slotted you at 5 PM."),
    ("booking", "You have the 5 PM slot."),
    ("booking", "The 5 PM slot belongs to you."),
    ("booking", "Your booking went through for 5 PM."),
    ("booking", "I have you at 5 PM."),
    ("booking", "See you at five."),
    ("booking", "Your spot at five is guaranteed."),
    ("booking", "The slot has your name."),
    ("booking", "The receptionist wrote your name beside five."),
    ("message", "The clinic can read your message now."),
    ("message", "Your note is visible to reception."),
    ("question", "I captured your question for staff."),
    ("question", "The question awaits the doctor."),
    ("cancel", "The booking has been voided."),
    ("cancel", "There is no appointment anymore."),
    ("cancel", "Your time has been released."),
    ("cancel", "We have undone the booking."),
    ("reschedule", "Six is your revised time."),
    ("reschedule", "Your visit has been brought forward to six."),
    ("reschedule", "Your original time has been replaced by six."),
    ("reschedule", "The calendar now shows six for you."),
    ("booking", "All set for five."),
    ("booking", "Your appointment is complete."),
    ("booking", "The clinic accepted your booking for five."),
    ("message", "It is saved for the clinic."),
    ("message", "Reception acknowledged your message."),
    ("question", "Reception acknowledged your question."),
    ("message", "Your note is on file."),
    ("question", "Your question is on file."),
    ("cancel", "Your visit won't happen."),
    ("cancel", "The doctor won't be seeing you."),
    ("cancel", "Your name was struck from the list."),
    ("cancel", "The appointment is closed."),
    ("reschedule", "Your new time is six."),
    ("reschedule", "Come at six, not five."),
    ("reschedule", "We have pushed it to six."),
    ("reschedule", "Your updated time is six."),
)


class _SpeechHandle:
    def __init__(
        self,
        *,
        interrupted: bool = False,
        playout_error: Exception | None = None,
    ) -> None:
        self.interrupted = interrupted
        self.playout_error = playout_error
        self.waited = False

    async def wait_for_playout(self) -> None:
        self.waited = True
        if self.playout_error is not None:
            raise self.playout_error


class _FakeSession:
    def __init__(
        self,
        language: str = "en",
        *,
        speech_handles: list[_SpeechHandle] | None = None,
    ) -> None:
        self.userdata = {
            "language": language,
            "wait_clips": [],
            "wait_fillers": ("One moment, please. [long pause]",),
        }
        self.said: list[tuple[str, dict]] = []
        self.speech_handles = list(speech_handles or [])
        self.returned_handles: list[_SpeechHandle] = []

    def say(self, text: str, **kwargs):
        self.said.append((text, kwargs))
        handle = (
            self.speech_handles.pop(0)
            if self.speech_handles
            else _SpeechHandle()
        )
        self.returned_handles.append(handle)
        return handle


class _Context:
    def __init__(self, language: str = "en") -> None:
        self.session = _FakeSession(language)
        self.pinned = False

    def disallow_interruptions(self) -> None:
        self.pinned = True


class _SessionAgent(VachanamAgent):
    @property
    def session(self):
        return self._test_session


class _FakeDB:
    def __init__(
        self,
        *,
        commit_error: Exception | None = None,
        rollback_error: Exception | None = None,
    ) -> None:
        self.added: list[object] = []
        self.execute = AsyncMock()
        self.commit = AsyncMock(
            side_effect=commit_error if commit_error is not None else None
        )
        self.rollback = AsyncMock(
            side_effect=rollback_error if rollback_error is not None else None
        )

    def add(self, value: object) -> None:
        self.added.append(value)


def _agent(
    state: SessionState,
    db,
    *,
    session=None,
    calendar_service=None,
    doctor_contexts=(),
) -> VachanamAgent:
    cls = _SessionAgent if session is not None else VachanamAgent
    # The production multilingual turn detector is bound to a LiveKit job
    # executor.  These boundary tests deliberately run without a job/network.
    with patch.object(agent_mod, "MultilingualModel", return_value=None):
        value = cls(
            instructions="test",
            state=state,
            db=db,
            room=None,
            calendar_service=calendar_service,
            meta_service=None,
            transfer_to="",
            lang_code=state.language or "en",
            doctor_contexts=doctor_contexts,
        )
    if session is not None:
        value._test_session = session
    return value


def _message(text: str):
    return SimpleNamespace(text_content=text, content=text, role="user")


def _doctor(
    doctor_id,
    *,
    name: str = "Dr Rao",
    booking_type: str = "appointment",
):
    return SimpleNamespace(
        id=doctor_id,
        name=name,
        booking_type=booking_type,
    )


def _booking_choice(
    token_id,
    doctor_id,
    *,
    patient_name: str = "Asha Patient",
    doctor_name: str = "Dr Rao",
    booking_date: str = "2026-08-28",
    appointment_time: str | None = "17:00",
    booking_type: str = "appointment",
    token_number: int | None = None,
) -> dict:
    return {
        "token_id": str(token_id),
        "patient_name": patient_name,
        "doctor": doctor_name,
        "doctor_id": str(doctor_id),
        "date": booking_date,
        "time": appointment_time,
        "booking_type": booking_type,
        "token_number": token_number,
        "status": "confirmed",
    }


async def _chunks(text: str, width: int = 7):
    for start in range(0, len(text), width):
        yield text[start : start + width]


async def _speech_boundary(
    text: str,
    language: str,
    *,
    state: SessionState | None = None,
    pending_action: str | None = None,
) -> str:
    language_safe = _guard_output_language_stream(_chunks(text), language)
    mutation_safe = _guard_unverified_action_speech_stream(
        language_safe,
        language,
        verified_state=state,
        pending_action=pending_action,
    )
    return "".join([part async for part in mutation_safe])


@pytest.mark.asyncio
@pytest.mark.parametrize("language", LANGUAGES)
async def test_native_booking_confirmation_question_survives_final_boundary(language):
    question = CONFIRMATION_QUESTIONS[language]
    assert await _speech_boundary(question, language) == question


@pytest.mark.asyncio
@pytest.mark.parametrize("language", LANGUAGES)
async def test_semantic_fake_booking_claim_is_blocked_in_every_language(language):
    claim = SEMANTIC_BOOKING_CLAIMS[language]
    output = await _speech_boundary(claim, language)
    assert output == build_booking_failure_text(language)
    assert output != claim


@pytest.mark.asyncio
@pytest.mark.parametrize("action, claim", ENGLISH_ACTION_CLAIMS)
async def test_common_fake_mutation_paraphrases_are_blocked(action, claim):
    output = await _speech_boundary(claim, "en", pending_action=action)
    expected = (
        build_booking_failure_text("en")
        if action == "booking"
        else build_mutation_failure_text("en", action)
    )
    assert output == expected
    assert output != claim


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action", "refusal"),
    (
        ("message", "I cannot record that message."),
        ("question", "I cannot log that question."),
        ("booking", "I cannot book that appointment."),
        ("booking", "I do not have permission to make appointments."),
        ("booking", "I am unable to help with that."),
    ),
)
async def test_model_cannot_refuse_supported_pending_action(action, refusal):
    output = await _speech_boundary(refusal, "en", pending_action=action)
    assert output == build_action_continue_text("en", action)
    assert output != refusal


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("language", "action", "refusal"),
    (
        ("te", "booking", "నేను ఆ అపాయింట్‌మెంట్ బుక్ చేయలేను."),
        ("hi", "booking", "मैं यह अपॉइंटमेंट बुक नहीं कर सकती।"),
        ("ta", "booking", "என்னால் அந்த அப்பாயின்ட்மென்ட்டை புக் செய்ய முடியாது."),
        ("kn", "booking", "ನಾನು ಆ ಅಪಾಯಿಂಟ್‌ಮೆಂಟ್ ಬುಕ್ ಮಾಡಲು ಸಾಧ್ಯವಿಲ್ಲ."),
        ("ml", "booking", "എനിക്ക് ആ അപ്പോയിന്റ്മെന്റ് ബുക്ക് ചെയ്യാൻ കഴിയില്ല."),
        ("mr", "booking", "मी ती अपॉइंटमेंट बुक करू शकत नाही."),
        ("bn", "booking", "আমি ওই অ্যাপয়েন্টমেন্ট বুক করতে পারি না।"),
        ("te", "message", "నేను ఆ సందేశాన్ని నమోదు చేయలేను."),
        ("hi", "question", "मैं वह सवाल दर्ज नहीं कर सकती।"),
        ("ta", "message", "என்னால் அந்த செய்தியை பதிவு செய்ய முடியாது."),
        ("kn", "question", "ಆ ಪ್ರಶ್ನೆಯನ್ನು ದಾಖಲಿಸಲು ಸಾಧ್ಯವಿಲ್ಲ."),
        ("ml", "message", "ആ സന്ദേശം രേഖപ്പെടുത്താൻ കഴിയില്ല."),
        ("mr", "question", "तो प्रश्न नोंदवू शकत नाही."),
        ("bn", "message", "আমি ওই বার্তা নথিভুক্ত করতে পারি না।"),
    ),
)
async def test_model_cannot_refuse_supported_action_in_any_locked_language(
    language, action, refusal
):
    output = await _speech_boundary(refusal, language, pending_action=action)
    assert output == build_action_continue_text(language, action)
    assert output != refusal


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "claim",
    (
        "Please come at five.",
        "Head over at five.",
        "Plan on seeing Dr Rao at five.",
        "Dr Rao will be waiting for you at five.",
        "Five is your time.",
        "You can show up at five.",
        "Be there at five.",
    ),
)
async def test_arrival_directives_cannot_imply_an_uncommitted_booking(claim):
    output = await _speech_boundary(claim, "en", pending_action="booking")
    assert output == build_booking_failure_text("en")
    assert output != claim


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "safe_dialogue",
    (
        "You asked for 5 PM.",
        "Shall I book your appointment at 5 PM?",
        "The 5 PM slot is available.",
    ),
)
async def test_booking_flow_dialogue_is_not_mistaken_for_fake_arrival(
    safe_dialogue,
):
    assert await _speech_boundary(
        safe_dialogue, "en", pending_action="booking"
    ) == safe_dialogue


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "claim",
    (
        "Consider it done.",
        "That is taken care of.",
        "Your request went through.",
        "Your request has gone through.",
        "Everything is sorted.",
        "We are good to go.",
        "It has been handled.",
    ),
)
@pytest.mark.parametrize(
    "action", ("booking", "message", "question", "cancel", "reschedule")
)
async def test_context_only_success_claims_cannot_complete_pending_action(
    action, claim
):
    output = await _speech_boundary(claim, "en", pending_action=action)
    expected = (
        build_booking_failure_text("en")
        if action == "booking"
        else build_mutation_failure_text("en", action)
    )
    assert output == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "speech",
    (
        "5 PM is available.",
        "Dr Rao is available at 5 PM.",
        "Would you like me to book the 5 PM slot?",
        "Nothing has been booked yet.",
        "Booking is temporarily unavailable; no appointment was created.",
    ),
)
async def test_pending_booking_guard_keeps_provisional_and_non_result_speech(speech):
    assert await _speech_boundary(
        speech, "en", pending_action="booking"
    ) == speech


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action", "question"),
    (
        ("booking", "Is my appointment booked at 5 PM?"),
        ("booking", "Was my appointment booked under Asha?"),
        ("question", "Is my question logged?"),
        ("cancel", "Was my appointment cancelled?"),
        ("reschedule", "Has my appointment been rescheduled?"),
    ),
)
async def test_status_questions_are_not_rewritten_as_false_failures(action, question):
    assert await _speech_boundary(
        question, "en", pending_action=action
    ) == question


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action", "claim"),
    (
        ("booking", "The appointment is booked."),
        ("booking", "Your 5 PM slot is confirmed."),
        ("message", "Your message was recorded."),
        ("cancel", "The appointment was cancelled."),
        ("reschedule", "The appointment was moved."),
    ),
)
async def test_mutation_firewall_is_safe_at_every_stream_split(action, claim):
    expected = (
        build_booking_failure_text("en")
        if action == "booking"
        else build_mutation_failure_text("en", action)
    )
    for split_at in range(1, len(claim)):
        async def split_stream():
            yield claim[:split_at]
            yield claim[split_at:]

        output = "".join([
            part
            async for part in _guard_unverified_action_speech_stream(
                split_stream(), "en", pending_action=action
            )
        ])
        assert output == expected, (action, claim, split_at)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "withdrawal",
    (
        "no, don't book it",
        "actually don't book it",
        "okay, leave it",
        "సరే వద్దులే",
        "ठीक है रहने दो",
    ),
)
async def test_latest_booking_withdrawal_overrides_sticky_consent(
    monkeypatch, withdrawal
):
    state = _booking_state()
    state.last_user_utterance = withdrawal
    agent = _agent(state, _FakeDB())
    context = _Context()
    doctor_id = uuid4()
    release_hold = AsyncMock()
    core_assign = AsyncMock()
    core_confirm = AsyncMock()
    monkeypatch.setattr(agent, "_release_hold", release_hold)
    monkeypatch.setattr(agent, "_resolve_doctor_id", AsyncMock(return_value=doctor_id))
    monkeypatch.setattr(agent_mod, "assign_token", core_assign)
    monkeypatch.setattr(agent_mod, "confirm_booking", core_confirm)

    result = await agent.confirm_booking(
        context=context,
        doctor_id=str(doctor_id),
        patient_name="Patient",
        booking_date=(date.today() + timedelta(days=7)).isoformat(),
        appointment_time="17:00",
        patient_age=30,
    )

    assert result["reason"] == "caller_declined"
    core_assign.assert_not_awaited()
    core_confirm.assert_not_awaited()
    release_hold.assert_awaited_once()
    assert state.caller_asked_to_book is False
    assert state.token_held is False


@pytest.mark.asyncio
async def test_reschedule_and_cancel_withdrawals_never_write(monkeypatch):
    patient_id = uuid4()
    state = SessionState(
        branch_id=uuid4(),
        patient_phone="+919999999999",
        identity_verified=True,
        verified_patient_ids={patient_id},
        caller_asked_to_reschedule=True,
        caller_asked_to_cancel=True,
        last_user_utterance="actually don't change it",
        language="en",
    )
    agent = _agent(state, _FakeDB())
    do_reschedule = AsyncMock()
    do_cancel = AsyncMock()
    monkeypatch.setattr(agent, "_do_reschedule", do_reschedule)
    monkeypatch.setattr(agent, "_do_cancel", do_cancel)

    with pytest.raises(ToolError, match="just said NO"):
        await agent.reschedule_booking(
            _Context(), str(uuid4()), "2026-08-30", "17:00"
        )
    do_reschedule.assert_not_awaited()

    state.last_user_utterance = "yes, skip it"
    with pytest.raises(ToolError, match="withdrew the cancellation"):
        await agent.cancel_booking(_Context(), str(uuid4()))
    do_cancel.assert_not_awaited()


@pytest.mark.asyncio
async def test_direct_cancel_request_cannot_bypass_final_confirmation(monkeypatch):
    patient_id = uuid4()
    doctor_id = uuid4()
    token_id = uuid4()
    choice = _booking_choice(token_id, doctor_id)
    state = SessionState(
        branch_id=uuid4(),
        patient_phone="+919999999999",
        identity_verified=True,
        verified_patient_ids={patient_id},
        verified_booking_choices={str(token_id): choice},
        caller_asked_to_cancel=True,
        last_user_utterance="cancel my appointment",
        language="en",
    )
    agent = _agent(state, _FakeDB())
    do_cancel = AsyncMock()
    monkeypatch.setattr(agent, "_do_cancel", do_cancel)
    monkeypatch.setattr(agent_mod, "AgentSession", _FakeSession)
    context = _Context()

    with pytest.raises(StopResponse):
        await agent.cancel_booking(context, str(uuid4()))

    do_cancel.assert_not_awaited()
    assert [text for text, _ in context.session.said] == [
        agent_mod.sanitize_for_tts(
            build_cancellation_confirmation_question("en", choice)
        )
    ]
    assert context.session.returned_handles[0].waited is True
    assert state.pending_confirmation == "cancel"
    assert state.cancellation_confirmation_granted is False
    assert state.cancellation_confirmation_snapshot == choice


@pytest.mark.asyncio
async def test_interrupted_booking_confirmation_playout_never_arms_or_writes(
    monkeypatch,
):
    doctor_id = uuid4()
    booking_day = (date.today() + timedelta(days=7)).isoformat()
    state = SessionState(
        branch_id=uuid4(),
        patient_phone="+919999999999",
        language="en",
        last_user_utterance=f"book Asha on {booking_day} at 5 PM",
        caller_asked_to_book=True,
        caller_booking_date=booking_day,
        caller_booking_times=("17:00",),
    )
    handle = _SpeechHandle(interrupted=True)
    context = _Context()
    context.session = _FakeSession("en", speech_handles=[handle])
    agent = _agent(
        state,
        _FakeDB(),
        calendar_service=object(),
        doctor_contexts=(_doctor(doctor_id),),
    )
    core_assign = AsyncMock()
    core_confirm = AsyncMock()
    monkeypatch.setattr(agent_mod, "AgentSession", _FakeSession)
    monkeypatch.setattr(agent_mod, "assign_token", core_assign)
    monkeypatch.setattr(agent_mod, "confirm_booking", core_confirm)

    with pytest.raises(StopResponse):
        await agent.confirm_booking(
            context,
            str(doctor_id),
            "Asha",
            booking_day,
            appointment_time="17:00",
        )

    expected = build_booking_confirmation_question(
        "en",
        booking_type="appointment",
        patient_name="Asha",
        doctor_name="Dr Rao",
        date_=date.fromisoformat(booking_day),
        time_=time(17, 0),
    )
    assert [text for text, _ in context.session.said] == [
        agent_mod.sanitize_for_tts(expected)
    ]
    assert handle.waited is True
    assert state.booking_confirmation_snapshot == {}
    assert state.pending_confirmation is None
    assert state.booking_confirmation_granted is False
    assert state.token_held is False
    core_assign.assert_not_awaited()
    core_confirm.assert_not_awaited()


@pytest.mark.asyncio
async def test_interrupted_cancellation_confirmation_playout_never_arms_or_writes(
    monkeypatch,
):
    patient_id = uuid4()
    doctor_id = uuid4()
    token_id = uuid4()
    choice = _booking_choice(token_id, doctor_id)
    state = SessionState(
        branch_id=uuid4(),
        patient_phone="+919999999999",
        identity_verified=True,
        verified_patient_ids={patient_id},
        verified_booking_choices={str(token_id): choice},
        caller_asked_to_cancel=True,
        last_user_utterance="cancel my appointment",
        language="en",
    )
    handle = _SpeechHandle(interrupted=True)
    context = _Context()
    context.session = _FakeSession("en", speech_handles=[handle])
    agent = _agent(state, _FakeDB())
    do_cancel = AsyncMock()
    monkeypatch.setattr(agent_mod, "AgentSession", _FakeSession)
    monkeypatch.setattr(agent, "_do_cancel", do_cancel)

    with pytest.raises(StopResponse):
        await agent.cancel_booking(context, str(uuid4()))

    assert [text for text, _ in context.session.said] == [
        agent_mod.sanitize_for_tts(
            build_cancellation_confirmation_question("en", choice)
        )
    ]
    assert handle.waited is True
    assert state.cancellation_confirmation_snapshot == {}
    assert state.pending_confirmation is None
    assert state.cancellation_confirmation_granted is False
    do_cancel.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancel_target_is_bound_to_caller_date_time_not_model_id(monkeypatch):
    patient_id = uuid4()
    doctor_id = uuid4()
    selected_id = uuid4()
    other_id = uuid4()
    selected = _booking_choice(
        selected_id,
        doctor_id,
        booking_date="2026-08-28",
        appointment_time="17:00",
    )
    other = _booking_choice(
        other_id,
        doctor_id,
        booking_date="2026-08-29",
        appointment_time="18:00",
    )
    state = SessionState(
        branch_id=uuid4(),
        patient_phone="+919999999999",
        identity_verified=True,
        verified_patient_ids={patient_id},
        verified_booking_choices={
            str(selected_id): selected,
            str(other_id): other,
        },
        caller_asked_to_cancel=True,
        caller_existing_date="2026-08-28",
        caller_existing_times=("17:00",),
        last_user_utterance="cancel my August 28 appointment at 5 PM",
        language="en",
    )
    context = _Context()
    agent = _agent(state, _FakeDB())
    do_cancel = AsyncMock()
    monkeypatch.setattr(agent_mod, "AgentSession", _FakeSession)
    monkeypatch.setattr(agent, "_do_cancel", do_cancel)

    with pytest.raises(StopResponse):
        await agent.cancel_booking(context, str(uuid4()))

    assert state.cancellation_confirmation_snapshot == selected
    assert state.pending_confirmation == "cancel"
    assert [text for text, _ in context.session.said] == [
        agent_mod.sanitize_for_tts(
            build_cancellation_confirmation_question("en", selected)
        )
    ]
    do_cancel.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancel_ambiguous_verified_choices_blocks_without_speech_or_write(
    monkeypatch,
):
    patient_id = uuid4()
    doctor_id = uuid4()
    first_id = uuid4()
    second_id = uuid4()
    state = SessionState(
        branch_id=uuid4(),
        patient_phone="+919999999999",
        identity_verified=True,
        verified_patient_ids={patient_id},
        verified_booking_choices={
            str(first_id): _booking_choice(first_id, doctor_id),
            str(second_id): _booking_choice(
                second_id,
                doctor_id,
                booking_date="2026-08-29",
                appointment_time="18:00",
            ),
        },
        caller_asked_to_cancel=True,
        last_user_utterance="cancel my appointment",
        language="en",
    )
    context = _Context()
    agent = _agent(state, _FakeDB())
    do_cancel = AsyncMock()
    monkeypatch.setattr(agent_mod, "AgentSession", _FakeSession)
    monkeypatch.setattr(agent, "_do_cancel", do_cancel)

    with pytest.raises(ToolError, match="Several or no confirmed bookings"):
        await agent.cancel_booking(context, str(uuid4()))

    assert context.session.said == []
    assert state.cancellation_confirmation_snapshot == {}
    assert state.pending_confirmation is None
    do_cancel.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model_reason",
    ("reschedule", "skip the receipt", "urgent admin override"),
)
async def test_arbitrary_cancel_reason_cannot_suppress_full_deterministic_receipt(
    monkeypatch,
    model_reason,
    caplog,
):
    patient_id = uuid4()
    doctor_id = uuid4()
    token_id = uuid4()
    choice = _booking_choice(token_id, doctor_id)
    state = SessionState(
        branch_id=uuid4(),
        patient_phone="+919999999999",
        identity_verified=True,
        verified_patient_ids={patient_id},
        verified_booking_choices={str(token_id): choice},
        caller_asked_to_cancel=True,
        cancellation_confirmation_granted=True,
        cancellation_confirmation_snapshot=dict(choice),
        pending_confirmation="cancel",
        last_user_utterance="yes",
        language="en",
    )
    context = _Context()
    agent = _agent(state, _FakeDB())
    do_cancel = AsyncMock(return_value={"success": True})
    monkeypatch.setattr(agent_mod, "AgentSession", _FakeSession)
    monkeypatch.setattr(agent, "_do_cancel", do_cancel)
    caplog.set_level("WARNING", logger="vachanam-agent")

    with pytest.raises(StopResponse):
        await agent.cancel_booking(context, str(uuid4()), reason=model_reason)

    assert "model_cancel_reason_ignored" in caplog.text
    assert model_reason not in caplog.text
    do_cancel.assert_awaited_once_with(
        str(token_id),
        reason="patient_cancelled_or_rescheduled_on_call",
    )
    expected_receipt = build_confirm_text(
        "en",
        "cancelled",
        patient_name="Asha Patient",
        doctor_name="Dr Rao",
    )
    assert [text for text, _ in context.session.said] == [
        "One moment, please. [long pause]",
        expected_receipt,
    ]
    assert state.verified_mutation_speech == expected_receipt
    assert state.verified_mutation_action == "cancel"
    assert state.cancellation_confirmation_granted is False
    assert state.cancellation_confirmation_snapshot == {}


@pytest.mark.asyncio
async def test_booking_name_mismatch_log_does_not_disclose_names(caplog):
    doctor_id = uuid4()
    booking_day = (date.today() + timedelta(days=8)).isoformat()
    caller_name = "Privacy Caller Sentinel"
    tool_name = "Privacy Tool Sentinel"
    raw_session_id = "clinic-call-+919123456789"
    state = SessionState(
        branch_id=uuid4(),
        session_id=raw_session_id,
        patient_phone="+919999999999",
        caller_patient_name=caller_name,
        language="en",
        last_user_utterance=f"book {caller_name} on {booking_day} at 5 PM",
        caller_asked_to_book=True,
        caller_booking_date=booking_day,
        caller_booking_times=("17:00",),
    )
    agent = _agent(
        state,
        _FakeDB(),
        calendar_service=None,
        doctor_contexts=(_doctor(doctor_id),),
    )
    caplog.set_level("ERROR", logger="vachanam-agent")

    with pytest.raises(ToolError, match="patient name does not match"):
        await agent.confirm_booking(
            _Context(),
            str(doctor_id),
            tool_name,
            booking_day,
            appointment_time="17:00",
        )

    assert "booking_patient_name_mismatch" in caplog.text
    assert caller_name not in caplog.text
    assert tool_name not in caplog.text
    assert raw_session_id not in caplog.text


@pytest.mark.asyncio
async def test_verified_receipt_is_one_use_but_a_fresh_identical_write_rearms_it():
    state = SessionState(language="en")
    receipt = build_clinic_question_ack("en")

    state.verified_mutation_speech = receipt
    state.verified_mutation_action = "question"
    assert await _speech_boundary(receipt, "en", state=state) == receipt
    assert state.verified_mutation_speech is None
    assert state.verified_mutation_action is None

    assert await _speech_boundary(receipt, "en", state=state) == (
        build_mutation_failure_text("en", "question")
    )

    # A second, genuinely committed question has the same generic acknowledgement.
    # Its fresh receipt must win over the replay ledger for this occurrence.
    state.verified_mutation_speech = receipt
    state.verified_mutation_action = "question"
    assert await _speech_boundary(receipt, "en", state=state) == receipt
    assert state.verified_mutation_speech is None
    assert state.verified_mutation_action is None


def _booking_state() -> SessionState:
    return SessionState(
        branch_id=uuid4(),
        patient_phone="+919999999999",
        language="en",
        last_user_utterance="please book it",
        caller_asked_to_book=True,
        booking_confirmation_granted=True,
        token_held=True,
        token_number=1,
        token_redis_key="slot:doctor:branch:day:1700",
        appointment_time="17:00",
    )


@pytest.mark.asyncio
async def test_confirmed_bound_booking_executes_without_model_tool_choice():
    doctor_id = uuid4()
    booking_day = (date.today() + timedelta(days=7)).isoformat()
    snapshot = {
        "patient_name": "Asha",
        "doctor_id": str(doctor_id),
        "doctor_name": "Dr Rao",
        "booking_date": booking_day,
        "appointment_time": "17:00",
        "booking_type": "appointment",
    }
    state = SessionState(
        branch_id=uuid4(),
        patient_phone="+919999999999",
        language="en",
        caller_asked_to_book=True,
        pending_confirmation="book",
        booking_confirmation_snapshot=snapshot.copy(),
    )
    db = _FakeDB()
    session = SimpleNamespace(
        userdata={},
        agent_state="listening",
        interrupt=Mock(),
        say=AsyncMock(),
    )
    agent = _agent(state, db, session=session)
    deterministic_confirm = AsyncMock(return_value={"success": True})
    agent.confirm_booking = deterministic_confirm

    with pytest.raises(StopResponse):
        await agent.on_user_turn_completed(ChatContext.empty(), _message("yes"))

    deterministic_confirm.assert_awaited_once()
    assert deterministic_confirm.await_args.kwargs == {
        "doctor_id": str(doctor_id),
        "patient_name": "Asha",
        "booking_date": booking_day,
        "appointment_time": "17:00",
    }
    context = deterministic_confirm.await_args.args[0]
    assert context.protected is True
    assert context.session is session
    assert state.booking_confirmation_granted is True


@pytest.mark.asyncio
async def test_confirmed_bound_booking_dependency_failure_never_reaches_model():
    doctor_id = uuid4()
    booking_day = (date.today() + timedelta(days=7)).isoformat()
    state = SessionState(
        branch_id=uuid4(),
        patient_phone="+919999999999",
        language="en",
        caller_asked_to_book=True,
        pending_confirmation="book",
        booking_confirmation_snapshot={
            "patient_name": "Asha",
            "doctor_id": str(doctor_id),
            "doctor_name": "Dr Rao",
            "booking_date": booking_day,
            "appointment_time": "17:00",
            "booking_type": "appointment",
        },
    )
    db = _FakeDB()
    session = SimpleNamespace(
        userdata={},
        agent_state="listening",
        interrupt=Mock(),
        say=AsyncMock(),
    )
    agent = _agent(state, db, session=session)
    agent.confirm_booking = AsyncMock(
        return_value={"success": False, "error": "booking_failed"}
    )

    with pytest.raises(StopResponse):
        await agent.on_user_turn_completed(ChatContext.empty(), _message("yes"))

    session.say.assert_awaited_once_with(
        build_booking_unavailable_text("en"),
        allow_interruptions=False,
    )


@pytest.mark.asyncio
async def test_confirmed_bound_booking_preserves_optional_family_fields():
    doctor_id = uuid4()
    booking_day = (date.today() + timedelta(days=7)).isoformat()
    snapshot = {
        "patient_name": "Maya",
        "doctor_id": str(doctor_id),
        "doctor_name": "Dr Rao",
        "booking_date": booking_day,
        "appointment_time": "17:00",
        "booking_type": "appointment",
        "complaint": "rash for two days",
        "followup_consent": False,
        "patient_age": 9,
        "patient_gender": "female",
        "different_person": True,
    }
    state = SessionState(
        branch_id=uuid4(),
        patient_phone="+919999999999",
        language="en",
        caller_asked_to_book=True,
        pending_confirmation="book",
        booking_confirmation_snapshot=snapshot,
    )
    session = SimpleNamespace(
        userdata={}, agent_state="listening", interrupt=Mock(), say=AsyncMock()
    )
    agent = _agent(state, _FakeDB(), session=session)
    deterministic_confirm = AsyncMock(return_value={"success": True})
    agent.confirm_booking = deterministic_confirm

    with pytest.raises(StopResponse):
        await agent.on_user_turn_completed(ChatContext.empty(), _message("yes"))

    assert deterministic_confirm.await_args.kwargs == {
        "doctor_id": str(doctor_id),
        "patient_name": "Maya",
        "booking_date": booking_day,
        "appointment_time": "17:00",
        "complaint": "rash for two days",
        "followup_consent": False,
        "patient_age": 9,
        "patient_gender": "female",
        "different_person": True,
    }


@pytest.mark.asyncio
async def test_confirmed_booking_yes_and_language_switch_apply_same_turn():
    doctor_id = uuid4()
    booking_day = (date.today() + timedelta(days=7)).isoformat()
    state = SessionState(
        branch_id=uuid4(),
        patient_phone="+919999999999",
        language="te",
        caller_asked_to_book=True,
        pending_confirmation="book",
        booking_confirmation_snapshot={
            "patient_name": "Asha",
            "doctor_id": str(doctor_id),
            "doctor_name": "Dr Rao",
            "booking_date": booking_day,
            "appointment_time": "17:00",
            "booking_type": "appointment",
        },
    )
    session = SimpleNamespace(
        userdata={"language": "te"},
        agent_state="listening",
        interrupt=Mock(),
        say=AsyncMock(),
    )
    agent = _agent(state, _FakeDB(), session=session)
    agent.confirm_booking = AsyncMock(return_value={"success": True})

    with pytest.raises(StopResponse):
        await agent.on_user_turn_completed(
            ChatContext.empty(), _message("yes, switch to English")
        )

    agent.confirm_booking.assert_awaited_once()
    assert state.language == "en"
    assert state.explicit_language_lock == "en"
    assert session.userdata["language"] == "en"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_mode", ("exception", "returned_unavailable"))
async def test_calendar_failure_speaks_before_blocked_cleanup_and_clears_state(
    monkeypatch,
    failure_mode,
):
    doctor_id = uuid4()
    booking_day = (date.today() + timedelta(days=7)).isoformat()
    branch_id = uuid4()
    expected_hold_key = agent_mod._reservation_key(
        doctor_id,
        branch_id,
        date.fromisoformat(booking_day),
        "appointment",
        time(17, 0),
    )
    state = SessionState(
        branch_id=branch_id,
        patient_phone="+919999999999",
        language="en",
        last_user_utterance="yes",
        caller_asked_to_book=True,
        caller_booking_date=booking_day,
        caller_booking_times=("17:00",),
        booking_confirmation_granted=True,
        booking_confirmation_snapshot={
            "patient_name": "Patient",
            "doctor_id": str(doctor_id),
            "doctor_name": "Dr Rao",
            "booking_date": booking_day,
            "appointment_time": "17:00",
            "booking_type": "appointment",
        },
        token_held=True,
        token_number=1,
        token_redis_key=expected_hold_key,
        appointment_time="17:00",
    )
    db = _FakeDB()
    agent = _agent(
        state,
        db,
        calendar_service=object(),
        doctor_contexts=(_doctor(doctor_id),),
    )
    context = _Context()
    monkeypatch.setattr(agent_mod, "AgentSession", _FakeSession)
    monkeypatch.setattr(agent, "_resolve_doctor_id", AsyncMock(return_value=doctor_id))

    if failure_mode == "exception":
        core = AsyncMock(side_effect=RuntimeError("calendar down"))
    else:
        core = AsyncMock(
            return_value={"success": False, "reason": "booking_system_unavailable"}
        )
    monkeypatch.setattr(agent_mod, "confirm_booking", core)

    release_started = asyncio.Event()
    allow_release = asyncio.Event()

    async def blocked_release(assigned):
        assert assigned == {"redis_key": expected_hold_key}
        release_started.set()
        await allow_release.wait()

    monkeypatch.setattr(agent, "_release_hold", blocked_release)
    task = asyncio.create_task(
        agent.confirm_booking(
            context=context,
            doctor_id=str(doctor_id),
            patient_name="Patient",
            booking_date=booking_day,
            appointment_time="17:00",
            patient_age=30,
        )
    )

    await asyncio.wait_for(release_started.wait(), timeout=1.0)
    assert not task.done()
    assert [text for text, _ in context.session.said] == [
        "One moment, please. [long pause]",
        build_booking_unavailable_text("en"),
    ]
    assert context.pinned is True
    assert state.token_held is False
    assert state.token_number is None
    assert state.token_redis_key is None
    assert state.token_confirmed is False
    assert state.pending_confirmation is None
    assert state.caller_asked_to_book is False
    assert state.verified_mutation_speech is None
    assert state.verified_mutation_action is None
    assert state.pending_clinic_message is not None
    assert "Patient" in state.pending_clinic_message
    assert booking_day in state.pending_clinic_message
    assert "17:00" in state.pending_clinic_message
    assert "no appointment was created" in state.pending_clinic_message

    allow_release.set()
    with pytest.raises(StopResponse):
        await task
    assert state.mutation_in_flight is None
    core.assert_awaited_once()
    if failure_mode == "exception":
        db.rollback.assert_awaited_once()
    else:
        db.rollback.assert_not_awaited()

    # A following yes binds take_message to the server-built snapshot even if
    # the model supplies a different paraphrase.
    snapshot = state.pending_clinic_message
    state.last_user_utterance = "yes"
    with pytest.raises(StopResponse):
        await agent.take_message(context, "model changed the request")
    assert db.added[-1].message == snapshot
    assert state.pending_clinic_message is None
    assert [text for text, _ in context.session.said][-1] == (
        build_clinic_message_ack("en")
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ("check", "assign", "confirm"))
async def test_disconnected_slot_calendar_fails_before_hold_write_or_question(
    monkeypatch,
    operation,
):
    doctor_id = uuid4()
    booking_day = (date.today() + timedelta(days=8)).isoformat()
    state = SessionState(
        branch_id=uuid4(),
        patient_phone="+919999999999",
        caller_patient_name="Asha",
        language="en",
        last_user_utterance=f"book Asha on {booking_day} at 5 PM",
        caller_asked_to_book=True,
        caller_booking_date=booking_day,
        caller_booking_times=("17:00",),
    )
    db = _FakeDB()
    context = _Context()
    agent = _agent(
        state,
        db,
        calendar_service=None,
        doctor_contexts=(_doctor(doctor_id),),
    )
    core_check = AsyncMock()
    core_assign = AsyncMock()
    core_confirm = AsyncMock()
    monkeypatch.setattr(agent_mod, "AgentSession", _FakeSession)
    monkeypatch.setattr(agent_mod, "check_availability", core_check)
    monkeypatch.setattr(agent_mod, "assign_token", core_assign)
    monkeypatch.setattr(agent_mod, "confirm_booking", core_confirm)

    with pytest.raises(StopResponse):
        if operation == "check":
            await agent.check_availability(
                context,
                str(doctor_id),
                booking_day,
                query_start="17:00",
                query_end="17:15",
            )
        elif operation == "assign":
            await agent.assign_token(
                context,
                str(doctor_id),
                booking_day,
                appointment_time="17:00",
            )
        else:
            await agent.confirm_booking(
                context,
                str(doctor_id),
                "Asha",
                booking_day,
                appointment_time="17:00",
            )

    core_check.assert_not_awaited()
    core_assign.assert_not_awaited()
    core_confirm.assert_not_awaited()
    db.commit.assert_not_awaited()
    assert [text for text, _ in context.session.said][-1] == (
        build_booking_unavailable_text("en")
    )
    assert all(
        "Shall I book" not in text
        for text, _ in context.session.said
    )
    assert state.token_held is False
    assert state.token_confirmed is False
    assert state.pending_confirmation is None
    assert state.booking_confirmation_snapshot == {}
    assert state.pending_clinic_message is not None
    assert "Asha" in state.pending_clinic_message
    assert "Dr Rao" in state.pending_clinic_message
    assert booking_day in state.pending_clinic_message
    assert "17:00" in state.pending_clinic_message
    assert "no appointment was created" in state.pending_clinic_message


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_date", "tool_time"),
    (("2026-08-31", "18:00"), ("2026-08-30", None)),
)
async def test_disconnected_calendar_message_uses_only_caller_date_time_receipts(
    monkeypatch,
    tool_date,
    tool_time,
):
    doctor_id = uuid4()
    state = SessionState(
        branch_id=uuid4(),
        patient_phone="+919999999999",
        caller_patient_name="Asha",
        language="en",
        caller_asked_to_book=True,
        caller_booking_date="2026-08-30",
        caller_booking_times=("17:00",),
    )
    agent = _agent(
        state,
        _FakeDB(),
        calendar_service=None,
        doctor_contexts=(_doctor(doctor_id),),
    )
    context = _Context()
    core = AsyncMock()
    monkeypatch.setattr(agent_mod, "AgentSession", _FakeSession)
    monkeypatch.setattr(agent_mod, "check_availability", core)
    monkeypatch.setattr(agent, "_resolve_doctor_id", AsyncMock(return_value=doctor_id))

    with pytest.raises(StopResponse):
        await agent.check_availability(
            context,
            str(doctor_id),
            tool_date,
            query_start=tool_time,
        )

    core.assert_not_awaited()
    assert "2026-08-30 at 17:00" in state.pending_clinic_message
    assert "2026-08-31" not in state.pending_clinic_message
    assert "18:00" not in state.pending_clinic_message


@pytest.mark.asyncio
async def test_disconnected_calendar_reschedule_fails_and_offers_exact_message(
    monkeypatch,
):
    patient_id = uuid4()
    doctor_id = uuid4()
    token_id = uuid4()
    choice = _booking_choice(token_id, doctor_id)
    state = SessionState(
        branch_id=uuid4(),
        patient_phone="+919999999999",
        identity_verified=True,
        verified_patient_ids={patient_id},
        verified_booking_choices={str(token_id): choice},
        caller_asked_to_reschedule=True,
        caller_reschedule_date="2026-08-30",
        caller_reschedule_times=("17:00",),
        last_user_utterance="Move it to August 30 at 5 PM",
        language="en",
    )
    agent = _agent(state, _FakeDB(), calendar_service=None)
    context = _Context()
    core = AsyncMock()
    monkeypatch.setattr(agent_mod, "AgentSession", _FakeSession)
    monkeypatch.setattr(agent, "_do_reschedule", core)

    with pytest.raises(StopResponse):
        await agent.reschedule_booking(
            context,
            str(token_id),
            "2026-08-30",
            "17:00",
        )

    core.assert_not_awaited()
    assert [text for text, _ in context.session.said][-1] == (
        build_booking_unavailable_text("en")
    )
    assert state.pending_clinic_message is not None
    assert "Reschedule request" in state.pending_clinic_message
    assert "2026-08-30 at 17:00" in state.pending_clinic_message
    assert "appointment was not moved" in state.pending_clinic_message


@pytest.mark.asyncio
async def test_token_queue_booking_remains_usable_without_slot_calendar(monkeypatch):
    doctor_id = uuid4()
    token_id = uuid4()
    patient_id = uuid4()
    booking_day = (date.today() + timedelta(days=9)).isoformat()
    branch_id = uuid4()
    expected_hold_key = agent_mod._reservation_key(
        doctor_id,
        branch_id,
        date.fromisoformat(booking_day),
        "token",
        None,
    )
    state = SessionState(
        branch_id=branch_id,
        patient_phone="+919999999999",
        language="en",
        last_user_utterance="yes",
        caller_asked_to_book=True,
        caller_booking_date=booking_day,
        booking_confirmation_granted=True,
        booking_confirmation_snapshot={
            "patient_name": "Asha",
            "doctor_id": str(doctor_id),
            "doctor_name": "Dr Queue",
            "booking_date": booking_day,
            "appointment_time": None,
            "booking_type": "token",
        },
    )
    context = _Context()
    agent = _agent(
        state,
        _FakeDB(),
        calendar_service=None,
        doctor_contexts=(
            _doctor(doctor_id, name="Dr Queue", booking_type="token"),
        ),
    )
    core_assign = AsyncMock(
        return_value={
            "success": True,
            "booking_type": "token",
            "token_number": 7,
            "redis_key": expected_hold_key,
        }
    )
    core_confirm = AsyncMock(
        return_value={
            "success": True,
            "token_id": str(token_id),
            "patient_id": str(patient_id),
            "announce": "token_number",
        }
    )
    monkeypatch.setattr(agent_mod, "AgentSession", _FakeSession)
    monkeypatch.setattr(agent_mod, "assign_token", core_assign)
    monkeypatch.setattr(agent_mod, "confirm_booking", core_confirm)

    with pytest.raises(StopResponse):
        await agent.confirm_booking(
            context,
            str(doctor_id),
            "model changed the name",
            booking_day,
            appointment_time="23:59",
        )

    core_assign.assert_awaited_once()
    core_confirm.assert_awaited_once()
    assert core_confirm.await_args.kwargs["doctor_id"] == doctor_id
    assert core_confirm.await_args.kwargs["patient_name"] == "Asha"
    assert core_confirm.await_args.kwargs["booking_date"] == date.fromisoformat(
        booking_day
    )
    assert core_confirm.await_args.kwargs["appointment_time"] is None
    assert core_confirm.await_args.kwargs["calendar_service"] is None
    expected_receipt = build_confirm_text(
        "en",
        "booked_token",
        token=7,
        date_=date.fromisoformat(booking_day),
        patient_name="Asha",
        doctor_name="Dr Queue",
    )
    assert [text for text, _ in context.session.said] == [
        "One moment, please. [long pause]",
        expected_receipt,
    ]
    assert state.token_confirmed is True
    assert state.last_confirmed_token_id == token_id
    assert state.verified_booking_choices[str(token_id)] == {
        "token_id": str(token_id),
        "patient_name": "Asha",
        "doctor": "Dr Queue",
        "doctor_id": str(doctor_id),
        "date": booking_day,
        "time": None,
        "token_number": 7,
        "booking_type": "token",
        "status": "confirmed",
    }


@pytest.mark.asyncio
async def test_failed_fallback_message_commit_keeps_exact_snapshot_for_retry(
    monkeypatch,
):
    snapshot = (
        "Booking request for Patient with Dr Rao on 2026-08-28 at 17:00. "
        "The voice booking system was temporarily unavailable; no appointment "
        "was created."
    )
    state = SessionState(
        branch_id=uuid4(),
        patient_phone="+919999999999",
        language="en",
        last_user_utterance="yes",
        pending_clinic_message=snapshot,
    )
    db = _FakeDB(commit_error=RuntimeError("database down"))
    agent = _agent(state, db)
    context = _Context()
    monkeypatch.setattr(agent_mod, "AgentSession", _FakeSession)

    with pytest.raises(StopResponse):
        await agent.take_message(context, "model changed the request")

    assert db.added[-1].message == snapshot
    assert state.pending_clinic_message == snapshot
    assert [text for text, _ in context.session.said] == [
        build_mutation_failure_text("en", "message")
    ]


@pytest.mark.asyncio
async def test_calendar_fallback_yes_persists_directly_without_model_tool_call(
    monkeypatch,
):
    snapshot = "Exact failed booking request from server state."
    state = SessionState(
        branch_id=uuid4(),
        patient_phone="+919999999999",
        language="en",
        pending_clinic_message=snapshot,
    )
    db = _FakeDB()
    context = _Context()
    agent = _agent(state, db, session=context.session)
    monkeypatch.setattr(agent_mod, "AgentSession", _FakeSession)

    with pytest.raises(StopResponse):
        await agent.on_user_turn_completed(ChatContext.empty(), _message("yes"))

    db.commit.assert_awaited_once()
    assert db.added[-1].message == snapshot
    assert state.pending_clinic_message is None
    assert [text for text, _ in context.session.said] == [
        build_clinic_message_ack("en")
    ]


@pytest.mark.asyncio
async def test_calendar_fallback_consent_applies_same_turn_language_switch(
    monkeypatch,
):
    snapshot = "Exact failed booking request from server state."
    state = SessionState(
        branch_id=uuid4(),
        patient_phone="+919999999999",
        language="te",
        pending_clinic_message=snapshot,
    )
    db = _FakeDB()
    context = _Context("te")
    agent = _agent(state, db, session=context.session)
    monkeypatch.setattr(agent_mod, "AgentSession", _FakeSession)

    with pytest.raises(StopResponse):
        await agent.on_user_turn_completed(
            ChatContext.empty(), _message("yes, switch to English")
        )

    db.commit.assert_awaited_once()
    assert db.added[-1].message == snapshot
    assert state.pending_clinic_message is None
    assert state.language == "en"
    assert state.explicit_language_lock == "en"
    assert [text for text, _ in context.session.said] == [
        build_clinic_message_ack("en")
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("language", "affirmation"),
    (
        ("en", "please do"),
        ("en", "that would be helpful"),
        ("en", "go for it"),
        ("te", "చేయండి"),
        ("hi", "कर दो"),
        ("ta", "செய்யுங்கள்"),
        ("kn", "ಮಾಡಿ"),
        ("mr", "करा"),
        ("bn", "করে দিন"),
    ),
)
async def test_calendar_fallback_direct_imperative_commits_exact_snapshot(
    monkeypatch, language, affirmation
):
    snapshot = "Exact failed booking request from server state."
    state = SessionState(
        branch_id=uuid4(),
        patient_phone="+919999999999",
        language=language,
        explicit_language_lock=language,
        pending_clinic_message=snapshot,
    )
    db = _FakeDB()
    context = _Context(language)
    agent = _agent(state, db, session=context.session)
    monkeypatch.setattr(agent_mod, "AgentSession", _FakeSession)

    with pytest.raises(StopResponse):
        await agent.on_user_turn_completed(
            ChatContext.empty(), _message(affirmation)
        )

    db.commit.assert_awaited_once()
    assert db.added[-1].message == snapshot
    assert state.pending_clinic_message is None
    assert [text for text, _ in context.session.said] == [
        build_clinic_message_ack(language)
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("language", "withdrawal"),
    (
        ("en", "okay, leave it"),
        ("en", "yes, skip it"),
        ("en", "sure, forget it"),
        ("en", "okay, I will call the clinic myself"),
        ("te", "సరే వద్దులే"),
        ("hi", "ठीक है रहने दो"),
        ("ta", "சரி வேண்டாம்"),
        ("kn", "ಸರಿ ಬೇಡ"),
        ("ml", "ശരി വേണ്ട"),
        ("mr", "बरं राहू द्या"),
        ("bn", "ঠিক আছে থাক"),
    ),
)
async def test_calendar_fallback_withdrawal_never_writes(
    monkeypatch, language, withdrawal
):
    state = SessionState(
        branch_id=uuid4(),
        patient_phone="+919999999999",
        language=language,
        explicit_language_lock=language,
        pending_clinic_message="Must never be written.",
    )
    db = _FakeDB()
    context = _Context(language)
    agent = _agent(state, db, session=context.session)
    monkeypatch.setattr(agent_mod, "AgentSession", _FakeSession)

    await agent.on_user_turn_completed(
        ChatContext.empty(), _message(withdrawal)
    )

    db.commit.assert_not_awaited()
    assert db.added == []
    assert state.pending_clinic_message is None
    assert context.session.said == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("language", "affirmation"),
    (("ml", "അതെ"), ("bn", "হ্যাঁ")),
)
async def test_native_affirmation_logs_calendar_fallback_snapshot(
    monkeypatch, language, affirmation
):
    snapshot = "Exact server-bound failed booking request."
    state = SessionState(
        branch_id=uuid4(),
        patient_phone="+919999999999",
        language="en",
        last_user_utterance=affirmation,
        pending_clinic_message=snapshot,
    )
    db = _FakeDB()
    agent = _agent(state, db)
    state.language = language
    agent._lang_code = language
    context = _Context(language)
    monkeypatch.setattr(agent_mod, "AgentSession", _FakeSession)

    with pytest.raises(StopResponse):
        await agent.take_message(context, "model changed the request")

    assert db.added[-1].message == snapshot
    assert state.pending_clinic_message is None
    assert [text for text, _ in context.session.said] == [
        build_clinic_message_ack(language)
    ]


async def _call_tool(agent: VachanamAgent, context: _Context, action: str):
    if action == "question":
        return await agent.log_clinic_question(
            context, "Does the clinic have a quiet sensory room?"
        )
    return await agent.take_message(
        context, "Please tell the doctor I need a callback.", urgent=False
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ("question", "message"))
async def test_question_and_message_commit_before_exact_verified_speech(
    monkeypatch,
    action,
):
    state = SessionState(
        branch_id=uuid4(),
        patient_phone="+919999999999",
        language="en",
    )
    db = _FakeDB()
    agent = _agent(state, db)
    context = _Context()
    monkeypatch.setattr(agent_mod, "AgentSession", _FakeSession)

    with pytest.raises(StopResponse):
        await _call_tool(agent, context, action)

    expected = (
        build_clinic_question_ack("en")
        if action == "question"
        else build_clinic_message_ack("en")
    )
    db.commit.assert_awaited_once()
    db.rollback.assert_not_awaited()
    assert context.pinned is True
    assert state.mutation_in_flight is None
    assert len(db.added) == 1
    assert [text for text, _ in context.session.said] == [expected]
    assert state.verified_mutation_speech == expected
    assert state.verified_mutation_action == action
    assert state.question_logged is (action == "question")
    assert state.message_taken is (action == "message")
    assert await _speech_boundary(expected, "en", state=state) == expected
    assert state.verified_mutation_speech is None
    assert state.verified_mutation_action is None


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ("question", "message"))
async def test_question_and_message_commit_failure_speaks_exact_non_result(
    monkeypatch,
    action,
):
    state = SessionState(
        branch_id=uuid4(),
        patient_phone="+919999999999",
        language="en",
    )
    db = _FakeDB(
        commit_error=RuntimeError("db down"),
        rollback_error=RuntimeError("rollback also down"),
    )
    agent = _agent(state, db)
    context = _Context()
    monkeypatch.setattr(agent_mod, "AgentSession", _FakeSession)

    with pytest.raises(StopResponse):
        await _call_tool(agent, context, action)

    expected = build_mutation_failure_text("en", action)
    db.commit.assert_awaited_once()
    db.rollback.assert_awaited_once()
    assert context.pinned is True
    assert state.mutation_in_flight is None
    assert [text for text, _ in context.session.said] == [expected]
    assert state.question_logged is False
    assert state.message_taken is False
    assert state.verified_mutation_speech is None
    assert state.verified_mutation_action is None
    assert await _speech_boundary(expected, "en", state=state) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ("question", "message"))
async def test_relay_yes_ignores_model_rewrite_and_commits_exact_caller_snapshot(
    monkeypatch,
    action,
):
    exact = (
        "What insurance plans does the clinic accept?"
        if action == "question"
        else "Please tell Dr Rao that I can wait until Monday."
    )
    state = SessionState(
        branch_id=uuid4(),
        patient_phone="+919999999999",
        language="en",
        last_user_utterance="yes",
        relay_snapshot_text=exact,
        relay_snapshot_kind=action,
    )
    db = _FakeDB()
    context = _Context()
    agent = _agent(state, db)
    monkeypatch.setattr(agent_mod, "AgentSession", _FakeSession)

    with pytest.raises(StopResponse):
        if action == "question":
            await agent.log_clinic_question(context, "model rewrote the question")
        else:
            await agent.take_message(
                context,
                "model rewrote the message",
                urgent=True,
            )

    db.commit.assert_awaited_once()
    assert len(db.added) == 1
    if action == "question":
        assert db.added[0].question == exact
        expected_ack = build_clinic_question_ack("en")
    else:
        assert db.added[0].message == exact
        assert db.added[0].urgent is False
        expected_ack = build_clinic_message_ack("en")
    assert [text for text, _ in context.session.said] == [expected_ack]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "command",
    (
        "Please log this question to the clinic",
        "Log my question for the clinic",
        "Record this question for the doctor",
        "Please note my question for the clinic",
    ),
)
async def test_direct_reference_question_persists_prior_words_not_command(
    monkeypatch,
    command,
):
    exact_question = "Does the clinic provide a quiet sensory room?"
    state = SessionState(
        branch_id=uuid4(),
        patient_phone="+919999999999",
        language="en",
    )
    db = _FakeDB()
    session = _FakeSession()
    agent = _agent(state, db, session=session)
    monkeypatch.setattr(agent_mod, "AgentSession", _FakeSession)

    await agent.on_user_turn_completed(
        ChatContext.empty(), _message(exact_question)
    )
    with pytest.raises(StopResponse):
        await agent.on_user_turn_completed(ChatContext.empty(), _message(command))

    db.commit.assert_awaited_once()
    assert len(db.added) == 1
    assert db.added[0].question == exact_question
    assert command not in db.added[0].question
    assert [text for text, _ in session.said] == [
        build_clinic_question_ack("en")
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "command",
    (
        "Please log that message for the clinic",
        "Record this message for the doctor",
        "Please note my message for the clinic",
    ),
)
async def test_direct_reference_message_persists_prior_words_not_command(
    monkeypatch,
    command,
):
    exact_message = "My rash is worse today and I need a callback."
    state = SessionState(
        branch_id=uuid4(),
        patient_phone="+919999999999",
        language="en",
    )
    db = _FakeDB()
    session = _FakeSession()
    agent = _agent(state, db, session=session)
    monkeypatch.setattr(agent_mod, "AgentSession", _FakeSession)

    await agent.on_user_turn_completed(
        ChatContext.empty(), _message(exact_message)
    )
    with pytest.raises(StopResponse):
        await agent.on_user_turn_completed(ChatContext.empty(), _message(command))

    db.commit.assert_awaited_once()
    assert len(db.added) == 1
    assert db.added[0].message == exact_message
    assert command not in db.added[0].message
    assert [text for text, _ in session.said] == [
        build_clinic_message_ack("en")
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("relay_request", "attribute", "payload", "expected_ack"),
    (
        (
            "Please tell the clinic that I need a callback.",
            "message",
            "I need a callback.",
            build_clinic_message_ack("en"),
        ),
        (
            "Please ask the clinic whether Dr Rao sees children.",
            "question",
            "whether Dr Rao sees children.",
            build_clinic_question_ack("en"),
        ),
    ),
)
async def test_explicit_direct_relay_executes_without_model_tool_choice(
    monkeypatch,
    caplog,
    relay_request,
    attribute,
    payload,
    expected_ack,
):
    state = SessionState(
        branch_id=uuid4(),
        patient_phone="+919999999999",
        language="en",
    )
    db = _FakeDB()
    session = _FakeSession()
    agent = _agent(state, db, session=session)
    monkeypatch.setattr(agent_mod, "AgentSession", _FakeSession)

    with pytest.raises(StopResponse):
        await agent.on_user_turn_completed(
            ChatContext.empty(), _message(relay_request)
        )

    db.commit.assert_awaited_once()
    assert getattr(db.added[0], attribute) == payload
    assert "please" not in getattr(db.added[0], attribute).casefold()
    assert [text for text, _ in session.said] == [expected_ack]
    assert "mutation_unprotected" not in caplog.text


@pytest.mark.asyncio
async def test_reference_relay_without_prior_text_asks_for_exact_content():
    state = SessionState(
        branch_id=uuid4(),
        patient_phone="+919999999999",
        language="en",
    )
    db = _FakeDB()
    session = SimpleNamespace(
        userdata={},
        agent_state="listening",
        interrupt=Mock(),
        say=AsyncMock(),
    )
    agent = _agent(state, db, session=session)

    with pytest.raises(StopResponse):
        await agent.on_user_turn_completed(
            ChatContext.empty(),
            _message("Please log this question to the clinic"),
        )

    db.commit.assert_not_awaited()
    assert db.added == []
    session.say.assert_awaited_once_with(
        build_relay_content_request_text("en", "question"),
        allow_interruptions=True,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("command", "kind"),
    (
        ("Tell clinic this", "message"),
        ("Ask doctor that", "message"),
        ("Send this to clinic", "message"),
        ("Please pass that to doctor", "message"),
    ),
)
async def test_pronoun_only_relay_command_never_becomes_stored_payload(
    command,
    kind,
):
    state = SessionState(branch_id=uuid4(), language="en")
    db = _FakeDB()
    session = SimpleNamespace(
        userdata={},
        agent_state="listening",
        interrupt=Mock(),
        say=AsyncMock(),
    )
    agent = _agent(state, db, session=session)

    with pytest.raises(StopResponse):
        await agent.on_user_turn_completed(ChatContext.empty(), _message(command))

    assert db.added == []
    db.commit.assert_not_awaited()
    session.say.assert_awaited_once_with(
        build_relay_content_request_text("en", kind),
        allow_interruptions=True,
    )


@pytest.mark.asyncio
async def test_direct_relay_wrong_kind_does_not_repurpose_prior_payload():
    state = SessionState(branch_id=uuid4(), language="en")
    db = _FakeDB()
    session = SimpleNamespace(
        userdata={},
        agent_state="listening",
        interrupt=Mock(),
        say=AsyncMock(),
    )
    agent = _agent(state, db, session=session)
    await agent.on_user_turn_completed(
        ChatContext.empty(), _message("Does the clinic have parking?")
    )

    with pytest.raises(StopResponse):
        await agent.on_user_turn_completed(
            ChatContext.empty(), _message("Record this message for the doctor")
        )

    assert db.added == []
    db.commit.assert_not_awaited()
    session.say.assert_awaited_once_with(
        build_relay_content_request_text("en", "message"),
        allow_interruptions=True,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "urgent_request",
    (
        "Tell the clinic I cannot breathe.",
        "Please tell the doctor I have severe chest pain.",
        "Tell the clinic to connect me to a human.",
    ),
)
async def test_escalation_priority_prevents_direct_relay_write(urgent_request):
    state = SessionState(branch_id=uuid4(), language="en")
    db = _FakeDB()
    session = _FakeSession()
    agent = _agent(state, db, session=session)
    transfer = AsyncMock(return_value={"success": True})
    agent.request_human_transfer = transfer
    turn_ctx = ChatContext.empty()

    with pytest.raises(StopResponse):
        await agent.on_user_turn_completed(turn_ctx, _message(urgent_request))

    assert db.added == []
    db.commit.assert_not_awaited()
    assert state.relay_snapshot_text is None
    assert any(
        "request_human_transfer" in str(getattr(item, "content", ""))
        for item in turn_ctx.items
    )
    transfer.assert_awaited_once()
    assert transfer.await_args.args[1] in {"urgent", "human"}
    with pytest.raises(ToolError):
        await agent.take_message(_Context(), urgent_request)
    assert db.added == []


@pytest.mark.asyncio
async def test_deterministic_transfer_failure_speaks_grounded_direct_path():
    state = SessionState(branch_id=uuid4(), language="en")
    db = _FakeDB()
    session = SimpleNamespace(
        userdata={},
        agent_state="listening",
        interrupt=Mock(),
        say=AsyncMock(),
    )
    agent = _agent(state, db, session=session)
    agent.request_human_transfer = AsyncMock(
        return_value={"success": False, "error": "transfer_unavailable"}
    )

    with pytest.raises(StopResponse):
        await agent.on_user_turn_completed(
            ChatContext.empty(), _message("Connect me to a human now.")
        )

    assert db.added == []
    session.say.assert_awaited_once_with(
        build_transfer_failure_text("en"),
        allow_interruptions=False,
    )


@pytest.mark.parametrize(
    "utterance",
    (
        "I do not want to speak to a human.",
        "Don't transfer me to a person.",
        "I can breathe.",
        "My chest pain is not severe.",
        "I am not suicidal.",
    ),
)
def test_clear_escalation_negation_never_triggers_transfer(utterance):
    assert agent_mod._caller_escalation_priority(utterance) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("request_text", "payload"),
    (
        (
            "Please ask the doctor if I should stop my medicine.",
            "if I should stop my medicine.",
        ),
        (
            "Please ask the doctor whether this pain needs attention.",
            "whether this pain needs attention.",
        ),
        (
            "Tell the doctor I missed a dose of my medicine.",
            "I missed a dose of my medicine.",
        ),
    ),
)
async def test_doctor_medical_question_routes_as_patient_message(
    monkeypatch,
    request_text,
    payload,
):
    state = SessionState(
        branch_id=uuid4(),
        patient_phone="+919999999999",
        language="en",
    )
    db = _FakeDB()
    session = _FakeSession()
    agent = _agent(state, db, session=session)
    monkeypatch.setattr(agent_mod, "AgentSession", _FakeSession)

    with pytest.raises(StopResponse):
        await agent.on_user_turn_completed(
            ChatContext.empty(), _message(request_text)
        )

    assert len(db.added) == 1
    assert db.added[0].message == payload
    assert not hasattr(db.added[0], "question")
    assert [text for text, _ in session.said] == [
        build_clinic_message_ack("en")
    ]


@pytest.mark.asyncio
async def test_prior_medical_words_then_ask_doctor_that_stays_a_message(
    monkeypatch,
):
    exact_payload = "I think I should stop my medicine."
    state = SessionState(
        branch_id=uuid4(),
        patient_phone="+919999999999",
        language="en",
    )
    db = _FakeDB()
    session = _FakeSession()
    agent = _agent(state, db, session=session)
    monkeypatch.setattr(agent_mod, "AgentSession", _FakeSession)

    await agent.on_user_turn_completed(
        ChatContext.empty(), _message(exact_payload)
    )
    with pytest.raises(StopResponse):
        await agent.on_user_turn_completed(
            ChatContext.empty(), _message("Ask the doctor that.")
        )

    assert len(db.added) == 1
    assert db.added[0].message == exact_payload
    assert not hasattr(db.added[0], "question")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "utterance",
    (
        "I will tell the clinic about this.",
        "If this fails I will report the clinic.",
        "Can you tell me whether the clinic is open?",
        "The clinic should know about messages.",
    ),
)
async def test_vague_relay_mentions_and_threats_never_write(utterance):
    state = SessionState(
        branch_id=uuid4(),
        patient_phone="+919999999999",
        language="en",
    )
    db = _FakeDB()
    session = _FakeSession()
    agent = _agent(state, db, session=session)

    try:
        await agent.on_user_turn_completed(
            ChatContext.empty(), _message(utterance)
        )
    except StopResponse:
        pass

    db.commit.assert_not_awaited()
    assert db.added == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "caller_message",
    (
        "Please tell Dr Rao this is not urgent; I can wait until Monday.",
        "This is not an emergency, please ask the doctor to call next week.",
        "There is no urgency; please leave the clinic a note.",
    ),
)
async def test_caller_urgency_negation_overrides_model_urgent_flag(
    monkeypatch,
    caller_message,
):
    state = SessionState(
        branch_id=uuid4(),
        patient_phone="+919999999999",
        language="en",
        last_user_utterance=caller_message,
    )
    db = _FakeDB()
    context = _Context()
    agent = _agent(state, db)
    notify = AsyncMock()
    monkeypatch.setattr(agent_mod, "AgentSession", _FakeSession)
    monkeypatch.setattr(
        "backend.services.support_email.notify_clinic_message",
        notify,
    )

    with pytest.raises(StopResponse):
        await agent.take_message(
            context,
            "model invented a different urgent message",
            urgent=True,
        )

    assert db.added[0].message == (
        agent_mod._caller_direct_relay_payload(caller_message) or caller_message
    )
    assert db.added[0].urgent is False
    notify.assert_not_awaited()
    assert [text for text, _ in context.session.said] == [
        build_clinic_message_ack("en")
    ]


@pytest.mark.asyncio
async def test_urgent_notification_cannot_delay_committed_message_ack(
    monkeypatch,
):
    state = SessionState(
        branch_id=uuid4(),
        patient_phone="+919999999999",
        patient_name="Patient",
        language="en",
    )
    db = _FakeDB()
    agent = _agent(state, db)
    context = _Context()
    monkeypatch.setattr(agent_mod, "AgentSession", _FakeSession)

    notification_started = asyncio.Event()
    allow_notification = asyncio.Event()
    notification_done = asyncio.Event()

    async def blocked_notification(*args, **kwargs):
        del args, kwargs
        notification_started.set()
        await allow_notification.wait()
        notification_done.set()

    monkeypatch.setattr(
        "backend.services.support_email.notify_clinic_message",
        blocked_notification,
    )

    with pytest.raises(StopResponse):
        await agent.take_message(
            context,
            "Please tell the doctor this is urgent.",
            urgent=True,
        )

    expected = build_clinic_message_ack("en")
    assert [text for text, _ in context.session.said] == [expected]
    assert state.message_taken is True
    db.commit.assert_awaited_once()

    await asyncio.wait_for(notification_started.wait(), timeout=1.0)
    assert notification_done.is_set() is False
    assert len(agent._background_tasks) == 1
    allow_notification.set()
    await asyncio.wait_for(notification_done.wait(), timeout=1.0)
    await asyncio.sleep(0)
    assert not agent._background_tasks

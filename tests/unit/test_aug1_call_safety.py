from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from agent.livekit_minimal.agent import (
    VachanamAgent,
    _caller_authorized_booking,
    _caller_authorized_cancellation,
    _caller_authorized_reschedule,
    _caller_rejected_accidental_booking,
    _explicit_language_request,
    _persist_call_language,
)
from agent.services.tts_sanitizer import sanitize_for_tts
from agent.services.meta_stub import MetaService
from agent.session_state import SessionState
from livekit.agents.llm import ChatContext


def _agent(state, *, calendar_service=None, doctor_contexts=None):
    return VachanamAgent(
        instructions='test', state=state, db=None, room=None,
        calendar_service=calendar_service, meta_service=MetaService(), transfer_to='',
        doctor_contexts=doctor_contexts,
    )


class _HandoffAgent(VachanamAgent):
    @property
    def session(self):
        return self._test_session


def test_availability_question_is_not_booking_authorization():
    assert not _caller_authorized_booking('మార్నింగ్ 10:00కి ఉంటారా?')
    assert not _caller_authorized_booking('Is the doctor available for booking at 10?')
    assert not _caller_authorized_booking('Can you confirm if the doctor is available?')
    assert not _caller_authorized_booking("Don't book it")
    assert not _caller_authorized_booking('Did you book it already?')
    assert _caller_authorized_booking('10:00కి బుక్ చేసేయండి')
    assert _caller_authorized_booking('Please book it at 10 AM')
    assert _caller_authorized_booking('Confirm the appointment at 10 AM')


def test_mutation_intents_are_distinct():
    assert _caller_authorized_cancellation('క్యాన్సిల్ చేయండి')
    assert not _caller_authorized_cancellation('10 గంటలకు ఉంటారా?')
    assert _caller_authorized_reschedule('టైమ్ మార్చండి')
    assert not _caller_authorized_reschedule('Is 11 AM available?')
    assert not _caller_authorized_cancellation("Don't cancel my appointment")
    assert not _caller_authorized_cancellation("I don't want to cancel")
    assert not _caller_authorized_cancellation('Did you cancel it already?')
    assert not _caller_authorized_cancellation('What is the cancellation policy?')
    assert not _caller_authorized_reschedule("Don't move the appointment")
    assert not _caller_authorized_reschedule("I do not want to reschedule")
    assert not _caller_authorized_reschedule('Did you reschedule it already?')
    assert not _caller_authorized_reschedule('What is the reschedule policy?')
    assert _caller_authorized_cancellation('Please cancel my appointment')
    assert _caller_authorized_reschedule('Please reschedule it to 11 AM')


def test_accidental_booking_rejection_and_language_request():
    assert _caller_rejected_accidental_booking('బుక్ చేయమని చెప్పలేదు')
    assert _explicit_language_request('తెలుగులో మాట్లాడండి') == 'te'
    assert _explicit_language_request('Can you speak English?') == 'en'
    assert _explicit_language_request('English doctor ఉన్నారా?') is None


@pytest.mark.asyncio
async def test_explicit_language_is_persisted_for_the_next_call(monkeypatch):
    from agent.livekit_minimal import agent as agent_mod

    state = SessionState(
        branch_id=uuid4(),
        patient_phone='+919876543210',
        language='en',
        preferred_language='en',
    )
    preference_db = object()

    class _PreferenceSession:
        async def __aenter__(self):
            return preference_db

        async def __aexit__(self, *_args):
            return False

    save = AsyncMock()
    monkeypatch.setattr(agent_mod, 'AsyncSessionLocal', _PreferenceSession)
    monkeypatch.setattr(agent_mod, 'set_preferred_language', save)

    assert await _persist_call_language(state, 'en') is True
    save.assert_awaited_once_with(
        state.branch_id, state.patient_phone, 'en', preference_db
    )


@pytest.mark.asyncio
async def test_language_request_updates_runtime_before_model_reply():
    state = SessionState(language='en', preferred_language='en')
    session = SimpleNamespace(userdata={}, updated_agent=None)
    session.update_agent = lambda value: setattr(session, 'updated_agent', value)
    replacement = SimpleNamespace(_tts_override=None)
    agent = _HandoffAgent(
        instructions='test', state=state, db=None, room=None,
        calendar_service=None, meta_service=MetaService(), transfer_to='',
        lang_code='en', agent_factory=lambda code, chat_ctx=None: replacement,
    )
    agent._test_session = session

    assert agent._handoff_explicit_language(ChatContext.empty(), 'te')
    await __import__('asyncio').sleep(0)

    assert state.language == 'te'
    assert state.preferred_language == 'te'
    assert session.userdata['language'] == 'te'
    assert session.updated_agent is replacement


def test_human_time_parser_accepts_natural_formats():
    assert VachanamAgent._parse_time('9 AM').isoformat() == '09:00:00'
    assert VachanamAgent._parse_time('9:30 pm').isoformat() == '21:30:00'
    assert VachanamAgent._parse_time('09:00').isoformat() == '09:00:00'


def test_bare_yes_requires_previous_audible_booking_question():
    state = SessionState(last_user_utterance='అవునండి')
    without_question = _agent(state)
    assert not without_question._last_assistant_requested_booking_confirmation()

    ctx = ChatContext.empty()
    ctx.add_message(
        role='assistant',
        content='ఆగస్టు నాలుగు 10:00కి బుక్ చేయనా?',
    )
    with_question = VachanamAgent(
        instructions='test', state=state, db=None, room=None,
        calendar_service=None, meta_service=MetaService(), transfer_to='',
        chat_ctx=ctx,
    )
    assert with_question._last_assistant_requested_booking_confirmation()


@pytest.mark.asyncio
async def test_availability_question_cannot_call_confirm_booking(monkeypatch):
    from livekit.agents import ToolError
    from agent.livekit_minimal import agent as agent_mod

    doctor_id = uuid4()
    state = SessionState(
        branch_id=uuid4(), patient_phone='+919999999999',
        last_user_utterance='మార్నింగ్ 10:00కి ఉంటారా?',
    )
    agent = _agent(
        state,
        calendar_service=object(),
        doctor_contexts=[
            SimpleNamespace(
                id=doctor_id, name='Dr Test', booking_type='appointment'
            )
        ],
    )
    core = AsyncMock(return_value={'success': True})
    monkeypatch.setattr(agent_mod, 'confirm_booking', core)
    # The INVARIANT is that asking "are you free at 10?" cannot write a booking.
    # The message changed 2026-08-03 (it now drives the confirmation question
    # instead of refusing aloud), so match on what must stay true, not on the
    # old sentence.
    with pytest.raises(ToolError) as blocked:
        await agent.confirm_booking(
            context=None, doctor_id=str(doctor_id), patient_name='Caller',
            complaint='dental', booking_date='2026-08-04',
            appointment_time='10:00',
        )
    text = str(blocked.value)
    assert 'exact booking confirmation question' in text
    core.assert_not_awaited()
    assert state.booking_confirmation_snapshot == {}
    assert state.token_confirmed is False


@pytest.mark.asyncio
async def test_accidental_reversal_is_pinned_to_exact_in_call_booking(monkeypatch):
    state = SessionState(
        branch_id=uuid4(), patient_phone='+919999999999',
        last_user_utterance='బుక్ చేయమని చెప్పలేదు',
            token_confirmed=True, last_confirmed_token_id=uuid4(),
            identity_verified=True,
            verified_patient_ids={uuid4()},
        )
    agent = _agent(state)
    do_cancel = AsyncMock(return_value={'success': True})
    monkeypatch.setattr(agent, '_do_cancel', do_cancel)

    older_booking = str(uuid4())
    result = await agent.cancel_booking(None, older_booking)

    assert result['success'] is True
    do_cancel.assert_awaited_once_with(
        str(state.last_confirmed_token_id),
        reason='patient_cancelled_or_rescheduled_on_call',
    )


def test_private_reasoning_and_markup_never_reach_tts():
    text = (
        'The caller wants doctor timings. I will use the available information. '
        '<private_context>secret</private_context>. Dr Rao is available at 10 AM.'
    )
    spoken = sanitize_for_tts(text)
    assert 'caller wants' not in spoken
    assert 'available information' not in spoken
    assert 'private_context' not in spoken
    assert 'Dr Rao is available' in spoken


def test_background_greeting_warmer_opens_livekit_http_context():
    import inspect
    import agent.livekit_minimal.agent as agent_module

    source = inspect.getsource(agent_module._start_prompt_cache_warmer)
    assert 'async with http_context.open()' in source
    assert 'asyncio.run(_warm_with_http_context())' in source

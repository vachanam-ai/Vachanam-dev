from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest
from livekit.agents import StopResponse
from livekit.agents.llm import ChatContext

from agent.livekit_minimal.agent import (
    VachanamAgent,
    _clearly_english_utterance,
    _guard_closed_booking_speech_stream,
)
from agent.services.meta_stub import MetaService
from agent.session_state import SessionState


class _Agent(VachanamAgent):
    @property
    def session(self):
        return self._test_session


def _agent(language='te', *, chat_ctx=None, factory=None):
    state = SessionState(language=language, preferred_language=language)
    agent = _Agent(
        instructions='test', state=state, db=None, room=None,
        calendar_service=None, meta_service=MetaService(), transfer_to='',
        lang_code=language, chat_ctx=chat_ctx, agent_factory=factory,
    )
    session = SimpleNamespace(
        userdata={}, agent_state='listening', updated_agent=None,
        say=AsyncMock(), interrupt=lambda: None,
    )
    session.update_agent = lambda value: setattr(session, 'updated_agent', value)
    agent._test_session = session
    return agent, state, session


def test_english_detection_requires_a_real_sentence_not_latin_script():
    assert _clearly_english_utterance('Can I book an appointment tomorrow?')
    assert _clearly_english_utterance('What time is the doctor available today?')
    assert _clearly_english_utterance("I'll let you know")
    assert _clearly_english_utterance('కెన్ యు రిపీట్ దట్ ఇన్ ఇంగ్లీష్, ప్లీజ్?')
    assert _clearly_english_utterance('ఓకే థాంక్యూ సో మచ్')
    assert not _clearly_english_utterance('repu doctor garu untara')
    assert not _clearly_english_utterance('డాక్టర్ గారు రేపు ఉంటారా')
    assert not _clearly_english_utterance('yes')


@pytest.mark.asyncio
async def test_yes_after_audible_booking_question_is_forced_to_confirm_not_reask():
    history = ChatContext.empty()
    history.add_message(
        role='assistant',
        content='Okay Vinay, shall I book 7 PM today with Dr. Srinivas?',
    )
    agent, state, _ = _agent('en', chat_ctx=history)
    turn = history.copy()

    await agent.on_user_turn_completed(
        turn, SimpleNamespace(content=['Yes, please.'])
    )

    assert state.pending_confirmation == 'book'
    assert state.caller_asked_to_book is True
    system_text = ' '.join(
        agent._message_text(item)
        for item in turn.items
        if getattr(item, 'role', None) == 'system'
    )
    assert 'then call confirm_booking immediately' in system_text
    assert 'Do not ask any confirmation question again' in system_text


@pytest.mark.asyncio
async def test_completed_booking_cannot_rearm_from_stale_assistant_question():
    history = ChatContext.empty()
    history.add_message(
        role='assistant',
        content='Vinay, you asked for 5 PM. Shall I book it?',
    )
    agent, state, _ = _agent('en', chat_ctx=history)
    state.token_confirmed = True
    state.any_booking_confirmed = True
    turn = history.copy()

    await agent.on_user_turn_completed(
        turn, SimpleNamespace(content=['You already booked it, right?'])
    )

    assert state.pending_confirmation is None
    assert state.caller_asked_to_book is False
    system_text = ' '.join(
        agent._message_text(item)
        for item in turn.items
        if getattr(item, 'role', None) == 'system'
    )
    assert 'most recent booking was committed successfully and is CLOSED' in system_text


@pytest.mark.asyncio
async def test_two_clear_english_turns_switch_the_whole_pipeline_to_english():
    replacement = SimpleNamespace(_tts_override=None)
    agent, state, session = _agent(
        'te', factory=lambda code, chat_ctx=None: replacement
    )

    await agent.on_user_turn_completed(
        ChatContext.empty(),
        SimpleNamespace(content=["I'll let you know"]),
    )
    assert state.language == 'te'
    assert state.language_candidate_turns == 1

    with pytest.raises(StopResponse):
        await agent.on_user_turn_completed(
            ChatContext.empty(),
            SimpleNamespace(content=['What time is the doctor available today?']),
        )

    assert state.language == 'en'
    assert state.preferred_language == 'en'
    assert session.updated_agent is replacement


def test_english_runtime_uses_an_english_close():
    from agent.i18n.lines import get_lines

    state = SessionState(language='en', preferred_language='en')
    assert get_lines(state.language).cap_goodbye == 'Thank you, have a good day!'
    assert 'జాగ్రత్తగా' not in get_lines(state.language).cap_goodbye


async def _chunks(*values):
    for value in values:
        yield value


@pytest.mark.asyncio
async def test_tts_firewall_replaces_stale_retry_before_it_is_spoken():
    output = [
        part async for part in _guard_closed_booking_speech_stream(
            _chunks(
                'I am sorry, it failed previously. ',
                'Shall I book your 5 PM appointment now?'
            ),
            'en',
        )
    ]
    speech = ''.join(output)
    assert speech == (
        'Your appointment is already confirmed. '
        'Is there anything else I can help with?'
    )
    assert 'failed' not in speech.casefold()
    assert 'shall i book' not in speech.casefold()


@pytest.mark.asyncio
async def test_closed_booking_tools_cannot_allocate_or_confirm_again():
    agent, state, _ = _agent('en')
    state.token_confirmed = True
    state.any_booking_confirmed = True
    state.last_user_utterance = 'What about parking?'

    held = await agent.assign_token(
        context=None,
        doctor_id='00000000-0000-0000-0000-000000000001',
        booking_date='2026-08-19',
        appointment_time='17:00',
    )
    confirmed = await agent.confirm_booking(
        context=None,
        doctor_id='00000000-0000-0000-0000-000000000001',
        patient_name='Vinay',
        booking_date='2026-08-19',
        appointment_time='17:00',
    )

    assert held['already_confirmed'] is True
    assert confirmed['already_confirmed'] is True
    assert state.token_confirmed is True
    assert state.token_held is False


@pytest.mark.asyncio
async def test_explicit_second_family_booking_opens_a_fresh_transaction():
    agent, state, _ = _agent('en')
    doctor_id = UUID('00000000-0000-0000-0000-000000000001')
    state.branch_id = UUID('00000000-0000-0000-0000-000000000002')
    state.token_confirmed = True
    state.any_booking_confirmed = True
    state.last_user_utterance = 'Please book another appointment for my wife.'
    state.caller_asked_to_book = True
    agent._resolve_doctor_id = AsyncMock(return_value=doctor_id)

    with patch(
        'agent.livekit_minimal.agent.assign_token',
        new=AsyncMock(return_value={
            'success': True,
            'booking_type': 'appointment',
            'token_number': 2,
            'redis_key': 'slot:test',
            'appointment_time': '17:00',
        }),
    ):
        result = await agent.assign_token(
            context=None,
            doctor_id=str(doctor_id),
            booking_date='2026-08-19',
            appointment_time='17:00',
        )

    assert result['success'] is True
    assert state.token_held is True
    assert state.token_confirmed is False

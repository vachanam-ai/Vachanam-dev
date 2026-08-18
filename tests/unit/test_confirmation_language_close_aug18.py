from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from livekit.agents import StopResponse
from livekit.agents.llm import ChatContext

from agent.livekit_minimal.agent import VachanamAgent, _clearly_english_utterance
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
async def test_two_clear_english_turns_switch_the_whole_pipeline_to_english():
    replacement = SimpleNamespace(_tts_override=None)
    agent, state, session = _agent(
        'te', factory=lambda code, chat_ctx=None: replacement
    )

    await agent.on_user_turn_completed(
        ChatContext.empty(),
        SimpleNamespace(content=['Can I book an appointment tomorrow?']),
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

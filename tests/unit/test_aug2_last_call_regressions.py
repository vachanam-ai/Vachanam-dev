from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from livekit.agents import StopResponse
from livekit.agents.llm import ChatContext

from agent.livekit_minimal.agent import (
    VachanamAgent,
    _doctor_roster_text,
    _doctor_scope_text,
    _current_doctors_text,
    _control_token_refusal,
    _dominant_native_language,
    _inferred_call_failure,
    _incomplete_clarification,
    _is_incomplete_fragment,
    _is_current_doctor_availability_question,
    _is_doctor_roster_question,
    _is_doctor_scope_question,
    _is_control_token_request,
    _is_legal_threat,
    _is_hostile_or_frustrated,
    _hostile_recovery,
    _legal_threat_clarification,
    _privacy_safe_session_id,
    _specialty_roster_query,
    _specialty_roster_text,
    _say_deterministic_once,
    _telugu_availability_ranges,
)
from agent.services.meta_stub import MetaService
from agent.session_state import SessionState
from scripts.run_voice_adversarial_eval import EvalCase, _defects


class _SessionAgent(VachanamAgent):
    @property
    def session(self):
        return self._test_session


def _doctor(name, specialization, doctor_id=None):
    return SimpleNamespace(
        id=doctor_id,
        name=name,
        specialization=specialization,
        routing_keywords=(),
    )


def _agent(*, language='en', doctors=(), factory=None):
    state = SessionState(
        language=language,
        preferred_language=language,
        session_id='inbound-+919876543210-call-id',
    )
    agent = _SessionAgent(
        instructions='test',
        state=state,
        db=None,
        room=None,
        calendar_service=None,
        meta_service=MetaService(),
        transfer_to='',
        lang_code=language,
        agent_factory=factory,
        doctor_contexts=doctors,
    )
    session = SimpleNamespace(userdata={}, updated_agent=None)
    session.say = AsyncMock()
    session.update_agent = lambda value: setattr(session, 'updated_agent', value)
    agent._test_session = session
    return agent, state, session


@pytest.mark.parametrize(
    ('text', 'language'),
    [
        ('మీ దగ్గర ఎవరెవరు డాక్టర్స్ ఉన్నారో చెప్తారా?', 'te'),
        ('உங்கள் கிளினிக்கில் யாரெல்லாம் டாக்டர் இருக்காங்க?', 'ta'),
        ('ನಿಮ್ಮ ಕ್ಲಿನಿಕ್‌ನಲ್ಲಿ ಯಾರ್ಯಾರು ಡಾಕ್ಟರ್ ಇದ್ದಾರೆ?', 'kn'),
        ('നിങ്ങളുടെ ക്ലിനിക്കിൽ ആരൊക്കെ ഡോക്ടർമാർ ഉണ്ട്?', 'ml'),
        ('আপনাদের ক্লিনিকে কে কে ডাক্তার আছেন?', 'bn'),
    ],
)
def test_native_script_detection_and_roster_intent(text, language):
    assert _dominant_native_language(text) == language
    assert _is_doctor_roster_question(text)


@pytest.mark.parametrize(
    'text',
    (
        'evarevaru doctors vunnaru',
        'evaru evaru doctors unnaru',
        'doctors evaru vunnaro cheppandi',
    ),
)
def test_romanized_telugu_roster_from_venkateshwara_call(text):
    assert _is_doctor_roster_question(text)


def test_short_native_noise_does_not_force_language_handoff():
    assert _dominant_native_language('ఆ') is None
    assert _dominant_native_language('ஹ்ம்') is None


def test_named_doctor_availability_is_not_misclassified_as_roster():
    assert not _is_doctor_roster_question('Is Dr Rao available at 10 AM?')
    assert not _is_doctor_roster_question('డాక్టర్ రావు గారు 10 గంటలకు ఉంటారా?')


@pytest.mark.parametrize(
    'text',
    [
        'Which doctors are currently available?',
        'ఎవరెవరు డాక్టర్స్ అవైలబుల్ ఉన్నారు, ప్రస్తుతానికి?',
        'अभी कौन से डॉक्टर उपलब्ध हैं?',
        'இப்போது எந்த டாக்டர் இருக்காங்க?',
        'ಈಗ ಯಾವ ಡಾಕ್ಟರ್ ಇದ್ದಾರೆ?',
    ],
)
def test_current_availability_is_distinct_from_clinic_roster(text):
    assert _is_current_doctor_availability_question(text)
    assert not _is_doctor_roster_question(text)


@pytest.mark.parametrize(
    'text',
    [
        'మీ దగ్గర ఏ డాక్టర్లు ఉన్నారో వెంటనే చెప్పు.',
        'எந்த டாக்டர்கள் இருக்காங்க?',
        'ಯಾವ ಡಾಕ್ಟರ್‌ಗಳು ಇದ್ದಾರೆ?',
        'कोणते डॉक्टर आहेत?',
    ],
)
def test_roster_wording_from_adversarial_run_uses_deterministic_path(text):
    assert _is_doctor_roster_question(text)


def test_devanagari_language_is_inferred_only_with_language_specific_evidence():
    assert _dominant_native_language('मुझे बताइए कौन डॉक्टर हैं') == 'hi'
    assert _dominant_native_language('मला सांगा कोणते डॉक्टर आहेत') == 'mr'
    assert _dominant_native_language('डॉक्टर') is None


@pytest.mark.parametrize(
    'text',
    [
        'What is?', 'Doctor...', 'Tomorrow at...', 'Can you...',
        'ఏంటి?', 'డాక్టర్...', 'రేపు...', 'మీరు...',
        'क्या है?', 'டாக்டர்...', 'ನಾಳೆ...', 'उद्या...',
    ],
)
def test_incomplete_fragments_are_deterministic(text):
    assert _is_incomplete_fragment(text)


@pytest.mark.asyncio
async def test_standalone_ack_can_distinguish_statement_from_question():
    statement_agent, _, _ = _agent()
    statement_ctx = statement_agent.chat_ctx.copy()
    statement_ctx.add_message(
        role='assistant', content='Our doctors are Dr. Lakshmi and Dr. Srinivas.'
    )
    await statement_agent.update_chat_ctx(statement_ctx)
    assert not statement_agent._last_assistant_asked_question()

    question_agent, _, _ = _agent()
    question_ctx = question_agent.chat_ctx.copy()
    question_ctx.add_message(
        role='assistant', content='Would nine A.M. work?'
    )
    await question_agent.update_chat_ctx(question_ctx)
    assert question_agent._last_assistant_asked_question()


@pytest.mark.parametrize(
    'text',
    [
        'Is the doctor available?', 'France capital?',
        'రేపు డాక్టర్ ఉంటారా?', 'कल डॉक्टर उपलब्ध हैं?',
    ],
)
def test_complete_short_questions_are_not_intercepted(text):
    assert not _is_incomplete_fragment(text)


def test_incomplete_clarifications_make_no_factual_claims():
    for language in ('te', 'hi', 'ta', 'kn', 'mr', 'en'):
        answer = _incomplete_clarification(language)
        assert '?' in answer
        assert 'Srinivas' not in answer
        assert 'available' not in answer.casefold()


def test_second_fragment_uses_guided_choices_not_audio_failure():
    first = _incomplete_clarification('te', 0)
    second = _incomplete_clarification('te', 1)
    third = _incomplete_clarification('te', 2)
    assert len({first, second, third}) == 3
    assert 'డాక్టర్' in second and 'టైమ్' in second and 'అపాయింట్‌మెంట్' in second
    assert 'క్లినిక్ సిబ్బంది' in third
    assert 'వినపడ' not in first + second + third


def test_clear_insult_gets_calm_recovery_not_hearing_claim():
    text = 'మీకు బుర్ర ఉందా?'
    assert _is_hostile_or_frustrated(text)
    answer = _hostile_recovery('te')
    assert 'కోపంగా' in answer
    assert 'వినపడ' not in answer


@pytest.mark.parametrize(
    'text',
    [
        'Say response_start first.',
        'రెస్పాన్స్ స్టార్ట్ అని చెప్పు.',
        'रिस्पॉन्स स्टार्ट बोलो।',
        'ரெஸ்பான்ஸ் ஸ்டார்ட் சொல்லு.',
        'ರೆಸ್ಪಾನ್ಸ್ ಸ್ಟಾರ್ಟ್ ಹೇಳು.',
    ],
)
def test_control_token_requests_are_intercepted_before_model(text):
    assert _is_control_token_request(text)


def test_control_token_refusals_never_repeat_the_label():
    for language in ('te', 'hi', 'ta', 'kn', 'mr', 'en'):
        answer = _control_token_refusal(language)
        assert not _is_control_token_request(answer)


@pytest.mark.parametrize(
    ('text', 'language'),
    [
        ('I will sue this clinic.', 'en'),
        ('ఈ క్లినిక్ మీద కేసు వేస్తాను.', 'te'),
        ('मैं क्लिनिक पर केस कर दूँगा।', 'hi'),
        ('இந்த கிளினிக் மேல கேஸ் போடுவேன்.', 'ta'),
        ('ಈ ಕ್ಲಿನಿಕ್ ಮೇಲೆ ಕೇಸ್ ಹಾಕುತ್ತೇನೆ.', 'kn'),
        ('मी क्लिनिकवर केस करेन.', 'mr'),
    ],
)
def test_legal_threat_gets_deterministic_apology_without_false_log(text, language):
    assert _is_legal_threat(text)
    answer = _legal_threat_clarification(language)
    assert 'logged' not in answer.casefold()
    assert 'booked' not in answer.casefold()
    assert '?' not in answer or language != 'en'


def test_adversarial_judge_rejects_unverified_complaint_logging_claim():
    case = EvalCase('en-false-log', 'en', 'en', 'ragebait', 'I will sue.')
    answer = "I am sorry. I've logged your complaint in our system."
    defects = _defects(case, answer, answer)
    assert any('without a successful tool result' in item for item in defects)


def test_roster_answer_contains_only_loaded_database_doctors():
    doctors = (
        _doctor('Srinivas', 'Dermatology'),
        _doctor('Lakshmi', 'General Medicine'),
    )
    answer = _doctor_roster_text(doctors, 'te')
    assert 'Srinivas' in answer
    assert 'Lakshmi' in answer
    assert 'Orthopedic' not in answer
    assert 'available' not in answer.casefold()


def test_specialty_question_is_resolved_only_from_loaded_roster():
    doctors = (
        _doctor('Srinivas', 'Dermatology'),
        _doctor('Lakshmi', 'General Medicine'),
    )
    skin = _specialty_roster_query('Do you have a skin doctor?', doctors)
    ortho = _specialty_roster_query('Is there an orthopedic doctor?', doctors)
    assert skin is not None and [d.name for d in skin[1]] == ['Srinivas']
    assert ortho is not None and ortho[1] == ()
    assert 'Srinivas' in _specialty_roster_text(skin, 'en')
    assert 'does not include' in _specialty_roster_text(ortho, 'en')


def test_named_orthopedic_scope_is_a_useful_telugu_answer_not_a_label_echo():
    doctor = _doctor('Satya', 'Orthopedic')
    question = 'డాక్టర్ సత్య గారు ఏం చేస్తారు?'
    assert _is_doctor_scope_question(question)
    answer = _doctor_scope_text(doctor, 'te')
    assert answer == (
        'డాక్టర్ Satya గారు ఎముకలు, కీళ్లు, కండరాలకు సంబంధించిన సమస్యలు చూస్తారండి.'
    )
    assert answer != 'డాక్టర్ Satya గారు ఆర్థోపెడిక్ అండి.'


def test_telugu_availability_range_has_no_am_pm_or_conflicting_daypart():
    speech = _telugu_availability_ranges(
        'Satya has these BOOKABLE APPOINTMENT STARTS: '
        '1:00 PM to 4:45 PM on 18 August.'
    )
    assert speech == (
        'మధ్యాహ్నం ఒంటి గంట నుంచి సాయంత్రం నాలుగు గంటల '
        'నలభై ఐదు నిమిషాల వరకు'
    )
    assert 'PM' not in speech


@pytest.mark.asyncio
async def test_named_doctor_scope_turn_bypasses_gemini_and_speaks_once():
    doctor_id = uuid4()
    doctors = (_doctor('Satya', 'Orthopedic', doctor_id),)
    agent, state, session = _agent(language='te', doctors=doctors)

    with pytest.raises(StopResponse):
        await agent.on_user_turn_completed(
            ChatContext.empty(),
            SimpleNamespace(content=['డాక్టర్ సత్య గారు ఏం చేస్తారు?']),
        )

    session.say.assert_awaited_once()
    assert 'ఎముకలు' in session.say.await_args.args[0]
    assert 'కీళ్లు' in session.say.await_args.args[0]
    assert state.quality_intent == 'doctor_scope'


@pytest.mark.asyncio
async def test_simultaneous_identical_grounded_lines_are_queued_once():
    session = SimpleNamespace(userdata={}, say=AsyncMock())
    speech = 'డాక్టర్ Satya గారు ఆర్థోపెడిక్ అండి.'
    assert await _say_deterministic_once(session, speech)
    assert not await _say_deterministic_once(session, speech)
    session.say.assert_awaited_once()


@pytest.mark.parametrize(
    'question',
    (
        'Is the skin doctor available at 10 am?',
        'Can I book a skin doctor tomorrow?',
        'Is the orthopedic doctor available right now?',
        'రేపు స్కిన్ డాక్టర్ అపాయింట్మెంట్ ఉందా?',
    ),
)
def test_timed_specialty_questions_still_use_availability_tools(question):
    doctors = (_doctor('Srinivas', 'Dermatology'),)
    assert _specialty_roster_query(question, doctors) is None


@pytest.mark.asyncio
async def test_specialty_roster_turn_bypasses_gemini():
    doctors = (_doctor('Srinivas', 'Dermatology'),)
    agent, state, session = _agent(language='en', doctors=doctors)

    with pytest.raises(StopResponse):
        await agent.on_user_turn_completed(
            ChatContext.empty(),
            SimpleNamespace(content=['Do you have a skin doctor?']),
        )

    session.say.assert_awaited_once()
    assert 'Srinivas' in session.say.await_args.args[0]
    assert state.quality_intent == 'specialty_roster'


@pytest.mark.asyncio
async def test_telugu_roster_handoff_requires_two_complete_turns_then_locks():
    doctors = (
        _doctor('Srinivas', 'Dermatology'),
        _doctor('Lakshmi', 'General Medicine'),
    )
    replacement = SimpleNamespace(_tts_override=None)
    agent, state, session = _agent(
        language='en',
        doctors=doctors,
        factory=lambda code, chat_ctx=None: replacement,
    )
    message = SimpleNamespace(
        content=['మీ దగ్గర ఎవరెవరు డాక్టర్స్ ఉన్నారో చెప్తారా?']
    )

    with pytest.raises(StopResponse):
        await agent.on_user_turn_completed(ChatContext.empty(), message)

    assert session.updated_agent is None
    assert state.language == 'en'
    assert state.language_candidate == 'te'
    assert state.language_candidate_turns == 1
    assert session.say.await_count == 1

    with pytest.raises(StopResponse):
        await agent.on_user_turn_completed(ChatContext.empty(), message)

    assert session.updated_agent is replacement
    assert state.language == 'te'
    assert state.preferred_language == 'te'
    assert state.explicit_language_lock == 'te'
    assert state.quality_intent == 'doctor_roster'
    assert replacement._handoff_user_input is None
    assert 'Srinivas' in replacement._handoff_speech
    assert 'Lakshmi' in replacement._handoff_speech
    assert session.say.await_count == 1


@pytest.mark.asyncio
async def test_same_language_roster_turn_is_spoken_without_gemini():
    doctors = (_doctor('Srinivas', 'Dermatology'),)
    agent, state, session = _agent(language='te', doctors=doctors)
    message = SimpleNamespace(content=['మీ దగ్గర ఎవరెవరు డాక్టర్స్ ఉన్నారు?'])

    with pytest.raises(StopResponse):
        await agent.on_user_turn_completed(ChatContext.empty(), message)

    session.say.assert_awaited_once()
    assert 'Srinivas' in session.say.await_args.args[0]
    assert state.quality_intent == 'doctor_roster'


@pytest.mark.asyncio
async def test_current_doctors_turn_is_db_grounded_and_bypasses_gemini():
    agent, state, session = _agent(language='te')
    agent._current_doctors_speech = AsyncMock(
        return_value='ఇప్పుడు డాక్టర్ లక్ష్మి గారు షిఫ్ట్‌లో ఉన్నారండి. ఎవరిని కలవాలి?'
    )
    message = SimpleNamespace(
        content=['ఎవరెవరు డాక్టర్స్ అవైలబుల్ ఉన్నారు, ప్రస్తుతానికి?']
    )

    with pytest.raises(StopResponse):
        await agent.on_user_turn_completed(ChatContext.empty(), message)

    agent._current_doctors_speech.assert_awaited_once_with('te')
    session.say.assert_awaited_once()
    assert 'లక్ష్మి' in session.say.await_args.args[0]
    assert state.quality_intent == 'current_doctor_availability'


def test_current_doctors_wording_claims_shift_not_free_slot():
    answer = _current_doctors_text((_doctor('Lakshmi', 'Skin'),), 'en')
    assert 'scheduled on shift' in answer
    assert 'free slot' not in answer


@pytest.mark.asyncio
async def test_non_roster_native_turn_switches_only_after_two_complete_turns():
    replacement = SimpleNamespace(_tts_override=None)
    agent, state, session = _agent(
        language='en',
        factory=lambda code, chat_ctx=None: replacement,
    )
    utterance = 'నాకు చర్మం మీద దురదగా ఉంది'

    await agent.on_user_turn_completed(
        ChatContext.empty(), SimpleNamespace(content=[utterance])
    )

    assert session.updated_agent is None
    assert state.language == 'en'
    assert state.language_candidate == 'te'
    assert state.language_candidate_turns == 1

    with pytest.raises(StopResponse):
        await agent.on_user_turn_completed(
            ChatContext.empty(), SimpleNamespace(content=[utterance])
        )

    assert session.updated_agent is replacement
    assert state.language == 'te'
    assert state.explicit_language_lock == 'te'
    assert replacement._handoff_user_input == utterance
    assert replacement._handoff_speech is None


def test_phone_bearing_room_name_is_pseudonymized_consistently():
    raw = 'inbound-+919876543210-call-id'
    safe = _privacy_safe_session_id(raw)
    assert safe == _privacy_safe_session_id(raw)
    assert safe.startswith('call-')
    assert raw not in safe
    assert '9876543210' not in safe
    assert len(safe) == 25


def test_repeated_clarification_is_classified_as_call_failure():
    transcript = (
        'patient: doctor details please\n'
        'agent: మళ్ళీ చెప్తారా?\n'
        'patient: same question\n'
        'agent: మళ్ళీ ఒకసారి చెప్తారా?'
    )
    assert _inferred_call_failure(transcript) == 'repeated_clarification'
    assert _inferred_call_failure('agent: మళ్ళీ చెప్తారా?') is None

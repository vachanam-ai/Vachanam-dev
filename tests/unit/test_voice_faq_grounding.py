from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from livekit.agents import StopResponse

from agent.livekit_minimal.agent import VachanamAgent, _naturalize_faq_match
from agent.livekit_minimal.faq_grounding import (
    FaqMatch,
    decode_faq,
    find_faq_match,
    natural_fallback,
)
from agent.services.meta_stub import MetaService
from agent.session_state import SessionState


FAQ = [{"q": "What is the consultation fee?", "a": "1000"}]


class _SessionAgent(VachanamAgent):
    @property
    def session(self):
        return self._test_session


def _agent(language="te"):
    agent = _SessionAgent(
        instructions="test",
        state=SessionState(language=language, session_id="faq-test"),
        db=None,
        room=None,
        calendar_service=None,
        meta_service=MetaService(),
        transfer_to="",
        lang_code=language,
        faq_rows=FAQ,
    )
    agent._test_session = SimpleNamespace(
        userdata={},
        agent_state="listening",
        say=AsyncMock(),
        interrupt=lambda: None,
    )
    return agent


def test_legacy_double_encoded_faq_is_decoded():
    assert decode_faq('"[{\\"q\\": \\"Fee?\\", \\"a\\": \\"100\\"}]"') == [
        {"q": "Fee?", "a": "100"}
    ]


@pytest.mark.parametrize(
    "utterance",
    [
        "What is Dr Chaitanya's consultation fee?",
        "డాక్టర్ చైతన్య గారి ఫీస్ ఎంత అండి?",
        "प्लास्टिक सर्जन की फीस कितनी है?",
    ],
)
def test_generic_fee_faq_semantically_covers_doctor_specific_wording(utterance):
    match = find_faq_match(utterance, FAQ)
    assert match == FaqMatch("What is the consultation fee?", "1000", "consultation_fee")


def test_bare_fee_value_gets_subject_and_currency_in_fallback():
    match = find_faq_match("ఫీస్ ఎంత?", FAQ)
    speech = natural_fallback(match, "te")
    assert "కన్సల్టేషన్ ఫీజు" in speech
    assert "1000 రూపాయలు" in speech


@pytest.mark.parametrize(
    "utterance",
    [
        (
            "I have a bike. At my previous clinic I had to park it outside; "
            "will I have the same problem at your clinic?"
        ),
        "parking vundha?",
        "నా బైక్ పెట్టుకోవడానికి అక్కడ ప్లేస్ ఉందా?",
        "क्या मेरी बाइक के लिए जगह है?",
    ],
)
def test_parking_faq_matches_direct_and_indirect_patient_wording(utterance):
    faq = [{"q": "Is parking available?", "a": "yes"}]
    assert find_faq_match(utterance, faq) == FaqMatch(
        "Is parking available?", "yes", "parking"
    )


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        ("te", "మా క్లినిక్‌లో పార్కింగ్ అందుబాటులో ఉంది"),
        ("en", "parking is available at the clinic"),
        ("hi", "क्लिनिक में पार्किंग उपलब्ध है"),
    ],
)
def test_bare_parking_yes_becomes_a_natural_localized_answer(language, expected):
    speech = natural_fallback(
        FaqMatch("Is parking available?", "yes", "parking"), language
    )
    assert speech.casefold() != "yes"
    assert expected.casefold() in speech.casefold()


def test_english_clinic_hours_row_has_complete_natural_telugu_fallback():
    match = FaqMatch(
        "What are the clinic timings? Are you open on Sundays?",
        "clinic timings are nine A.M. to 5. sundays close",
        "clinic_hours",
    )
    speech = natural_fallback(match, "te")
    assert speech == (
        "మా క్లినిక్ ఉదయం తొమ్మిది గంటల నుంచి సాయంత్రం ఐదు గంటల వరకు "
        "తెరిచి ఉంటుందండి. Sunday రోజు సెలవు అండి."
    )
    assert "clinic timings" not in speech.casefold()
    assert "a.m" not in speech.casefold()


@pytest.mark.asyncio
async def test_common_faq_renderer_skips_second_llm_hop():
    match = FaqMatch("Clinic timings?", "9 AM to 5 PM", "clinic_hours")
    with patch("agent.livekit_minimal.agent._localize_message", new=AsyncMock()) as localize:
        speech = await _naturalize_faq_match(match, "te")
    localize.assert_not_awaited()
    assert "ఉదయం" in speech and "సాయంత్రం" in speech


@pytest.mark.asyncio
async def test_parking_renderer_is_deterministic_and_skips_llm():
    match = FaqMatch("Is parking available?", "yes", "parking")
    with patch("agent.livekit_minimal.agent._localize_message", new=AsyncMock()) as localize:
        speech = await _naturalize_faq_match(match, "te")
    localize.assert_not_awaited()
    assert "పార్కింగ్ అందుబాటులో ఉంది" in speech


@pytest.mark.asyncio
async def test_known_faq_is_spoken_without_running_full_agent_or_logging_question():
    agent = _agent("en")
    turn = SimpleNamespace(add_message=lambda **_: None, items=[])
    message = SimpleNamespace(content=["What is Dr Chaitanya's consultation fee?"])
    with patch(
        "agent.livekit_minimal.agent._naturalize_faq_match",
        new=AsyncMock(return_value="కన్సల్టేషన్ ఫీజు 1000 రూపాయలు అండి."),
    ):
        with pytest.raises(StopResponse):
            await agent.on_user_turn_completed(turn, message)
    agent.session.say.assert_awaited_once()
    assert agent._state.quality_intent == "clinic_faq"

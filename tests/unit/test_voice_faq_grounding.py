from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from livekit.agents import StopResponse

from agent.livekit_minimal.agent import VachanamAgent
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

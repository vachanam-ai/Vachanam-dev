"""Cross-language regressions for DB-grounded deterministic voice answers."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from agent.livekit_minimal.agent import (
    _doctor_roster_text,
    _doctor_scope_text,
    _explicit_language_request,
    _naturalize_faq_match,
)
from agent.livekit_minimal.faq_grounding import FaqMatch, natural_fallback
from agent.prompts.grounded_prompt import supported_codes


SERVICEABLE_LANGUAGES = ("te", "hi", "en")
VOICE_LANGUAGES = SERVICEABLE_LANGUAGES


def test_prompt_covers_every_serviceable_production_language():
    assert supported_codes() == SERVICEABLE_LANGUAGES


@pytest.mark.parametrize("language", VOICE_LANGUAGES)
@pytest.mark.parametrize(
    "answer",
    (
        "clinic timings are nine A.M. to 5. sundays close",
        "8:15 AM to 12:30 PM",
        "1 PM to 4:45 PM",
    ),
)
def test_clinic_hours_never_read_the_raw_database_row(language, answer):
    speech = natural_fallback(FaqMatch("Clinic timings?", answer, "clinic_hours"), language)
    assert "clinic timings" not in speech.casefold()
    if language != "en":
        assert "a.m" not in speech.casefold()
        assert "p.m" not in speech.casefold()
        assert " am" not in speech.casefold()
        assert " pm" not in speech.casefold()
    assert len(speech.split()) >= 5


@pytest.mark.parametrize(
    ("language", "currency"),
    (
        ("te", "రూపాయలు"), ("hi", "रुपये"), ("ta", "ரூபாய்"),
        ("kn", "ರೂಪಾಯಿ"), ("mr", "रुपये"), ("en", "rupees"),
    ),
)
def test_fee_fallback_uses_the_active_languages_currency_word(language, currency):
    speech = natural_fallback(
        FaqMatch("What is the consultation fee?", "1000", "consultation_fee"),
        language,
    )
    assert "1000" in speech
    assert currency in speech
    if language not in ("te", "en"):
        assert "రూపాయలు" not in speech


@pytest.mark.parametrize("language", VOICE_LANGUAGES)
@pytest.mark.parametrize(
    "specialty",
    (
        "Dermatology", "Orthopedic", "Pediatrics", "Gynecology", "ENT",
        "Dentistry", "Ophthalmology", "Cardiology", "General Medicine",
        "Plastic Surgery",
    ),
)
def test_named_doctor_scope_explains_work_instead_of_echoing_label(language, specialty):
    doctor = SimpleNamespace(name="Dr. Satya", specialization=specialty, routing_keywords=())
    speech = _doctor_scope_text(doctor, language)
    assert speech != _doctor_roster_text((doctor,), language)
    assert "Satya" in speech
    assert len(speech) > len(specialty) + len("Dr. Satya") + 8


@pytest.mark.parametrize("language", VOICE_LANGUAGES)
@pytest.mark.parametrize("intent", ("clinic_hours", "consultation_fee"))
@pytest.mark.asyncio
async def test_common_facts_never_wait_for_a_second_llm(language, intent):
    answer = "9 AM to 5 PM" if intent == "clinic_hours" else "1000"
    match = FaqMatch("Clinic fact?", answer, intent)
    with patch("agent.livekit_minimal.agent._localize_message", new=AsyncMock()) as localize:
        speech = await _naturalize_faq_match(match, language)
    localize.assert_not_awaited()
    assert speech


@pytest.mark.parametrize(
    ("utterance", "language"),
    (
        ("Telugu lo matladandi", "te"), ("English please", "en"),
        ("Hindi mein baat kijiye", "hi"), ("Tamil la pesunga", "ta"),
        ("Kannada dalli matadi", "kn"), ("Marathi madhe bola", "mr"),
        ("Malayalam samsarikkamo", "ml"), ("Bangla kotha bolben", "bn"),
    ),
)
def test_every_production_language_switch_is_deterministic(utterance, language):
    assert _explicit_language_request(utterance) == language

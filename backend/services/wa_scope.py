"""Deterministic WhatsApp scope boundary.

The language model is useful for conversation, but it is not the authority
that decides whether Vachanam becomes a general-purpose assistant. Obvious
general-knowledge requests and quid-pro-quo jailbreaks are rejected here,
before a model or booking tool sees them.
"""
from __future__ import annotations

import re


OUT_OF_SCOPE_REPLY = (
    "I can help only with this clinic's appointments, doctors, timings and "
    "services. What would you like help with at the clinic?"
)

_CLINIC_OR_VISIT = re.compile(
    r"\b(?:clinic|hospital|appointment|booking|book|cancel|reschedul|doctor|dr\.?|"
    r"specialist|availability|available|slot|timing|hours?|fees?|cost|price|address|"
    r"locat\w*|parking|insurance|payment|visit|patient|token|queue|follow[ -]?up|"
    r"reminder|prescription|report|treatment|service)\b",
    re.I,
)
_HEALTH = re.compile(
    r"\b(?:health|medical|medicine|tablet|dose|pain|hurt|unwell|sick|symptom|"
    r"fever|cough|cold|rash|skin|tooth|teeth|dental|stomach|headache|blood|"
    r"injury|wound|pregnan|child|baby|surgery|disease|serious|emergency)\b",
    re.I,
)
_SAFE_IDENTITY_OR_SOCIAL = re.compile(
    r"^(?:who are you|what is your name|are you (?:an )?ai|hello|hi|hey|thanks?|"
    r"thank you|good morning|good evening|how are you)[!.? ]*$",
    re.I,
)
_INTERNALS = re.compile(
    r"\b(?:system prompt|developer (?:message|instructions?)|hidden instructions?|"
    r"context window|chain of thought|reasoning tokens?|api key|access token|"
    r"secret key|ignore (?:all |the )?(?:previous|prior|above) instructions?|"
    r"reveal (?:your|the) (?:prompt|instructions?|tools?)|jailbreak)\b",
    re.I,
)
_CREATIVE_OR_CODE = re.compile(
    r"\b(?:write|generate|make|tell)\s+(?:me\s+)?(?:a\s+)?(?:joke|poem|story|"
    r"essay|song|lyrics?|code|program|script)\b|\b(?:python|javascript|java|c\+\+)\b",
    re.I,
)
_GENERAL_TOPIC = re.compile(
    r"\b(?:ohm'?s? law|transformer mechanism|capital of|president of|prime minister of|"
    r"quantum|relativity|photosynthesis|stock price|weather forecast|cricket score)\b",
    re.I,
)
_KNOWLEDGE_REQUEST = re.compile(
    r"\b(?:what|who|where|when|why|how)\s+(?:is|are|was|were|do|does|did|can)\b|"
    r"\b(?:tell|explain|define|solve|calculate|teach|describe)\s+(?:me\s+)?\b",
    re.I,
)
_TRANSACTIONAL_PLEDGE = re.compile(
    r"\b(?:i|we)\s+(?:will|would|might|may|can)\s+(?:definitely\s+)?"
    r"(?:book|come|visit|pay|reconsider)\b",
    re.I,
)
_ARITHMETIC = re.compile(r"(?<![\w:])\d+(?:\.\d+)?\s*(?:\+|\*|=)\s*\d+(?:\.\d+)?")


def is_out_of_scope(text: str) -> bool:
    """Return True only for high-confidence non-clinic requests."""
    value = " ".join((text or "").casefold().split())
    if not value:
        return False
    if _INTERNALS.search(value):
        return True
    if _SAFE_IDENTITY_OR_SOCIAL.search(value):
        return False

    has_clinic_subject = bool(_CLINIC_OR_VISIT.search(value))
    has_health_subject = bool(_HEALTH.search(value))
    if _ARITHMETIC.search(value) and not (has_clinic_subject or has_health_subject):
        return True
    # Adding "for the clinic" to a joke, code or textbook request does not
    # change its subject. These high-confidence categories are always refused.
    if _CREATIVE_OR_CODE.search(value) or _GENERAL_TOPIC.search(value):
        return True

    # "Explain X and I will book" is not a booking request. Only the part
    # before the promised booking is the requested subject.
    pledge = _TRANSACTIONAL_PLEDGE.search(value)
    if pledge:
        requested_subject = value[: pledge.start()]
        if _KNOWLEDGE_REQUEST.search(requested_subject) and not (
            _CLINIC_OR_VISIT.search(requested_subject)
            or _HEALTH.search(requested_subject)
        ):
            return True

    # Very short fragments ("what is?") remain conversational so the agent
    # can ask for clarification.
    if (
        _KNOWLEDGE_REQUEST.search(value)
        and len(re.findall(r"[\w']+", value)) >= 3
        and not (has_clinic_subject or has_health_subject)
    ):
        return True
    return False

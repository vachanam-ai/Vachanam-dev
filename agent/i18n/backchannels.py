"""Backchannel lexicon — listening noises that must NEVER interrupt the agent.

Vinay 2026-07-04: "in each language there will be some words people use to make
sure they are available or listening (aha, okay, hmm, acha) — the agent should
not get interrupted by those." The agent's turn-loop interrupts on the FIRST
transcribed word (min_interruption_words=1, deliberate — a real interruption
must stop the agent fast), so the filter lives at the STT event layer: while
the agent is SPEAKING, a transcript that is ONLY backchannel tokens is dropped
before the interruption gate ever counts its words.

Deliberately EXCLUDED: answer words (అవును, సరే, yes, no, हाँ jī as consent…)
are only suppressed as part of this set when they are pure listening signals —
we keep the set to sounds/acks that are near-never a standalone answer. హా/ఆ
and haan ARE also used as "yes", but mid-agent-speech they are overwhelmingly
backchannels; when the agent is silent they pass through untouched (the filter
only runs while the agent is speaking).
"""
import re

# Universal sounds (Latin STT renderings) + per-script listening tokens.
_TOKENS: frozenset[str] = frozenset({
    # universal / English
    "ok", "okay", "kay", "hmm", "hmmm", "hm", "mm", "mmm", "mhm", "mmhm",
    "uh", "huh", "uhhuh", "aha", "ah", "aah", "oh", "ohh", "oho", "um",
    "right", "haan", "han", "ha", "haa", "aa", "acha", "accha", "achha",
    # Telugu
    "ఓకే", "ఆ", "ఆఁ", "ఊ", "హా", "హ్మ్", "అచ్చా", "ఓహో", "హు",
    # Hindi / Marathi (Devanagari)
    "हाँ", "हां", "हा", "हम्म", "हम्", "अच्छा", "अच्छ", "ओके", "ओह", "अहा",
    # Tamil
    "ம்", "ம்ம்", "ஆமா்", "ஓகே", "ஆ",
    # Kannada
    "ಹಾ", "ಹೂಂ", "ಓಕೆ", "ಅಚ್ಚಾ",
    # Malayalam
    "ഉം", "ആ", "ഓകെ", "ഹാ",
    # Bengali
    "হুম", "আচ্ছা", "হ্যাঁ", "ওকে",
    # Odia
    "ହଁ", "ଆଚ୍ଛା", "ଓକେ",
})

_STRIP = re.compile(r"[\s\.,!?;:'\"()\-–—]+")


def is_backchannel(text: str | None) -> bool:
    """True when the utterance is NOTHING BUT listening noises (max 3 tokens).

    "okay" -> True; "okay okay" -> True; "okay cancel it" -> False;
    "no no wait" -> False (real interruption content passes)."""
    tokens = [t for t in _STRIP.split((text or "").lower()) if t]
    if not tokens or len(tokens) > 3:
        return False
    return all(t in _TOKENS for t in tokens)


def suppress_backchannel(text: str | None, agent_speaking: bool) -> bool:
    """The filter decision: drop the transcript event ONLY when the agent is
    mid-speech AND the utterance is pure backchannel. When the agent is silent
    the same word is a real (short) turn and passes through."""
    return bool(agent_speaking) and is_backchannel(text)

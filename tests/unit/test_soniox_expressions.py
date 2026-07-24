"""Closed Soniox expression controls and fallback safety."""
from __future__ import annotations

import asyncio
from pathlib import Path

from agent.livekit_minimal import agent as ag

_SRC = Path("agent/livekit_minimal/agent.py").read_text(encoding="utf-8")


def test_strip_leading_expression_tag():
    assert ag._strip_expression_tags("[Happy] అద్భుతం!") == "అద్భుతం!"


def test_strip_multiple_tags():
    assert ag._strip_expression_tags("[Excited] ఓహ్! [Whisper] ఒక సూచన") == "ఓహ్! ఒక సూచన"


def test_no_tag_unchanged():
    assert ag._strip_expression_tags("నమస్కారం చెప్పండి") == "నమస్కారం చెప్పండి"


def test_digit_bracket_not_stripped():
    # only [Letter…] emotion tags are removed; a bracketed number stays put
    assert ag._strip_expression_tags("token [12] okay") == "token [12] okay"


def test_strip_handles_arbitrary_open_set_tags():
    # Smallest strips every bracketed stage direction, supported or not.
    assert ag._strip_expression_tags("[giggles] హహ") == "హహ"
    assert ag._strip_expression_tags("[angrily] ఇది తప్పు") == "ఇది తప్పు"
    assert ag._strip_expression_tags("[Concerned] అయ్యో") == "అయ్యో"


def test_strip_handles_full_soniox_vocabulary():
    """Vinay 2026-07-24: the real Soniox expression vocabulary is lowercase,
    sometimes multi-word ([takes a deep breath], [long pause], [clears throat]).
    Every form must strip clean on the smallest fallback."""
    for tag in ("[laughs]", "[whispers]", "[softly]", "[happily]", "[excitedly]",
                "[sighs]", "[takes a deep breath]", "[long pause]",
                "[clears throat]", "[hesitates]", "[pause]"):
        assert ag._strip_expression_tags(f"{tag} నమస్కారం") == "నమస్కారం", tag
    # mid-sentence too
    assert ag._strip_expression_tags("సరే [pause] చూస్తాను") == "సరే చూస్తాను"
    # "..." hesitation is TEXT, not a tag — must pass through untouched
    assert ag._strip_expression_tags("అది... చూడాలి") == "అది... చూడాలి"


def test_both_smallest_paths_strip_tags():
    """Strip is wired into BOTH smallest entry points (streaming + REST fallback)
    so a Soniox outage never reads a tag aloud."""
    guarded = _SRC.split("class _GuardedSmallestStream")[1].split("\nclass ", 1)[0]
    assert "_strip_expression_tags(text)" in guarded  # streaming WS path
    http = _SRC.split("class _HttpSmallestTTS")[1].split("\nclass ", 1)[0]
    assert "_strip_expression_tags(" in http           # REST fallback path


def test_soniox_path_keeps_tags():
    """The Soniox builder must NOT strip — tags are its whole point."""
    soniox = _SRC.split("def _build_soniox_tts")[1].split("\ndef ", 1)[0]
    assert "_strip_expression_tags" not in soniox


def test_closed_soniox_allowlist_is_exact():
    expected = {
        "[laughs]", "[giggles]", "[chuckles]", "[whispers]", "[softly]",
        "[shouts]", "[angrily]", "[happily]", "[sadly]", "[crying]",
        "[sighs]", "[takes a deep breath]", "[gasps]", "[nervously]",
        "[excitedly]", "[confused]", "[surprised]", "[relieved]",
        "[thinking]", "[hesitates]", "[pause]", "[long pause]",
        "[clears throat]", "[coughs]", "[yawns]", "[sobs]", "[sniffs]",
    }
    assert ag.SONIOX_EXPRESSION_TAGS == expected


def test_soniox_filter_keeps_exact_supported_and_strips_invented_tags():
    assert ag._filter_soniox_expression_tags("[softly] hello") == "[softly] hello"
    assert ag._filter_soniox_expression_tags("[Concerned] hello") == "hello"
    assert ag._filter_soniox_expression_tags("[Happy] hello") == "hello"
    assert ag._filter_soniox_expression_tags("token [12]") == "token [12]"


def test_soniox_filter_is_chunk_split_safe():
    async def source():
        for chunk in ("[sof", "tly] hello [Con", "cerned] there"):
            yield chunk

    async def collect():
        return "".join([c async for c in ag._filter_soniox_expression_stream(source())])

    assert asyncio.run(collect()) == "[softly] hello there"


def test_prompt_teaches_closed_optional_expressions_and_phone_digit_rule():
    p = Path("agent/prompts/grounded_prompt.py").read_text(encoding="utf-8")
    for tag in ("[happily]", "[excitedly]", "[whispers]", "[sighs]",
                "[takes a deep breath]", "[long pause]"):
        assert tag in p, tag
    assert "CLOSED allowlist" in p
    assert "only permitted non-spoken controls" in p
    assert "Most replies use NO tag" in p
    assert "at most ONE tag" in p
    assert "Never use laughter for pain" in p
    assert "PLAIN DIGITS" in p

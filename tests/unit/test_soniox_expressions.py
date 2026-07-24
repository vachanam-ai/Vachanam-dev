"""Closed Soniox expression controls and fallback safety."""
from __future__ import annotations

import asyncio
from pathlib import Path

from agent.livekit_minimal import agent as ag

_SRC = Path("agent/livekit_minimal/agent.py").read_text(encoding="utf-8")


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


def test_prompt_teaches_job_scoped_expressions_and_phone_digit_rule():
    p = Path("agent/prompts/grounded_prompt.py").read_text(encoding="utf-8")
    for tag in ("[softly]", "[happily]", "[relieved]", "[thinking]",
                "[hesitates]", "[confused]", "[sighs]", "[chuckles]",
                "[pause]", "[long pause]"):
        assert tag in p, tag
    assert "only these are ever earned" in p
    assert "No other tag exists in this job" in p
    assert "most replies carry neither instrument" in p
    assert "Never two emotions in one reply" in p
    assert "No laughter over pain" in p or "NEVER LAUGH over pain" in p
    assert "PLAIN DIGITS" in p
    assert "runtime supplies the hold line" in p
    assert "never generate" in p
    assert "routine [long pause] yourself" in p

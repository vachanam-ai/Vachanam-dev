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
        "[hesitates]", "[pause]", "[long pause]",
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
    for tag in ("[softly]", "[happily]", "[relieved]",
                "[hesitates]", "[confused]", "[sighs]", "[chuckles]",
                "[pause]"):
        assert tag in p, tag
    assert "[thinking]" not in p
    assert "Max ONE emotion tag per reply" in p
    assert "ALLOWED EMOTION TAGS:" in p
    assert "[chuckles] only if caller joked first" in p
    assert "Phone numbers are single spoken digits" in p

    # Long pauses are deterministic runtime hold audio, not model-generated
    # content. Every supported language must have at least one such filler.
    from agent.i18n.lines import WAIT_FILLERS

    assert WAIT_FILLERS
    for code, fillers in WAIT_FILLERS.items():
        assert any("[long pause]" in line for line in fillers), code

"""Soniox expression tags (Vinay 2026-07-24). The LLM prefixes replies with a
Soniox emotion tag ([Happy] [Excited] [Questioning] [Whisper]); Soniox speaks
them expressively. On the smallest.ai FALLBACK the tags are STRIPPED — a literal
"[Happy]" must never reach a caller (RULE 6). Only the confirmed tag set is
allowed so an unsupported tag can't be spoken literally by Soniox.
"""
from __future__ import annotations

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


def test_prompt_teaches_expressions_and_keeps_digit_rule():
    p = Path("agent/prompts/grounded_prompt.py").read_text(encoding="utf-8")
    for tag in ("[Happy]", "[Excited]", "[Questioning]", "[Whisper]"):
        assert tag in p, tag
    # the load-bearing "write digits, not native number words" rule must survive
    assert "DIGITS" in p

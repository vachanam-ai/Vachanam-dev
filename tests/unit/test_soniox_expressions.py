"""Soniox expression tags (Vinay 2026-07-24). The LLM prefixes replies with a
bracketed emotion tag ([Happy], [Excited], [Giggles], [Angry], [Whisper]…);
Soniox acts them. The set is OPEN — the prompt gives examples and lets the LLM
use any short emotion that fits (Vinay: "there are n expressions, don't limit").
On the smallest.ai FALLBACK ANY such tag is STRIPPED — a literal "[Happy]" must
never reach a caller (RULE 6) — so open-endedness is safe on the fallback.
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


def test_strip_handles_arbitrary_open_set_tags():
    # the set is OPEN — the strip must remove ANY emotion tag, not a fixed list,
    # so a novel/lowercase tag never leaks to the smallest fallback (RULE 6).
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


def test_prompt_teaches_expressions_open_set_and_keeps_digit_rule():
    p = Path("agent/prompts/grounded_prompt.py").read_text(encoding="utf-8")
    # teaches the REAL Soniox vocabulary (lowercase, incl multi-word forms)…
    for tag in ("[happily]", "[excitedly]", "[whispers]", "[sighs]",
                "[takes a deep breath]", "[long pause]"):
        assert tag in p, tag
    # …explicitly OPEN (Vinay: don't limit), pushed toward human-ness,
    # with the taste guard (never laugh at pain).
    assert "NOT limited" in p
    assert "SOUND HUMAN" in p
    assert "pain or bad news" in p
    # the load-bearing "write digits, not native number words" rule must survive
    assert "DIGITS" in p

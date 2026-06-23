"""C2 — naturalness judge for the humanizer.

Scores a phone transcript on how indistinguishable-from-human it is, against the
receptionist rules R1–R9 (docs/research/receptionist-rules-te.md). Two layers:

1. DETERMINISTIC pronunciation flags (no LLM): any romanized/Latin token in the
   agent's Telugu lines — TTS will SPELL those (RULE 6 violation). Placeholders
   ({clinic}…) are template-time and ignored.
2. LLM-as-judge (Gemini) for the qualitative rubric: warmth, honorifics/register,
   active-listening restate, turn-taking/backchannels, prosody, appointment flow,
   de-escalation correctness, anti-patterns, and overall human_likeness (1–5),
   with concrete suggestions.

The judge is an automated proxy to iterate fast; Vinay is the final arbiter on
real calls.
"""
from __future__ import annotations

import json
import re
import time

import structlog

from agent.i18n.te_gen import DEFAULT_MODEL, _client, _parse

logger = structlog.get_logger()

_PLACEHOLDER = re.compile(r"\{[^}]*\}")
_LATIN = re.compile(r"[A-Za-z]{2,}")

_RUBRIC = """You are judging whether a Telugu clinic receptionist on the phone sounds like a real warm human, not a bot. Rules: warm honorific greeting; గారు/అండి/మీరు register; restate the caller's need before acting; natural turn-taking + backchannels + short lines; spoken (not literary); offer 2-3 slots then confirm once; de-escalate angry/anxious callers WITHOUT giving medical advice; avoid robotic over-confirmation/monologue.

Score the transcript. Return ONLY JSON:
{"scores": {"warmth": 0-5, "honorifics": 0-5, "active_listening": 0-5, "turn_taking": 0-5, "prosody": 0-5, "appointment_flow": 0-5, "deescalation": 0-5, "anti_patterns": 0-5}, "human_likeness": 0-5, "suggestions": ["concrete fix", ...]}
anti_patterns is 5 when NONE are present. If the agent gives medical advice/diagnosis, deescalation must be 0 and add a suggestion."""


def pronunciation_flags(text: str) -> list[str]:
    """Romanized tokens TTS will spell out (RULE 6). Placeholders ignored."""
    stripped = _PLACEHOLDER.sub(" ", text or "")
    return _LATIN.findall(stripped)


def _agent_turns(transcript: list[dict]) -> list[str]:
    return [t.get("text", "") for t in transcript if t.get("role") in ("agent", "assistant")]


def score_naturalness(
    transcript: list[dict],
    *,
    client=None,
    model: str = DEFAULT_MODEL,
    retries: int = 4,
) -> dict:
    """Score a transcript (list of {role, text}). Combines deterministic
    pronunciation flags with the LLM rubric. Retries on transient Gemini 503."""
    flags: list[str] = []
    for line in _agent_turns(transcript):
        flags.extend(pronunciation_flags(line))

    prompt = _RUBRIC + "\n\nTranscript (JSON):\n" + json.dumps(transcript, ensure_ascii=False)
    client = client or _client()
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            resp = client.models.generate_content(model=model, contents=prompt)
            judged = _parse(resp.text)
            break
        except Exception as e:  # noqa: BLE001
            last_err = e
            logger.warning("naturalness_attempt_failed", attempt=attempt + 1, error=str(e)[:120])
            time.sleep(min(2 ** attempt, 8))
    else:
        raise RuntimeError(f"naturalness judge failed after {retries}: {last_err}")

    judged["pronunciation_flags"] = flags
    # A romanized token is an objective defect — surface it in suggestions.
    if flags:
        judged.setdefault("suggestions", []).append(
            f"Romanized tokens will be spelled by TTS — write in Telugu script: {flags}"
        )
    return judged

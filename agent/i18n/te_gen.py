"""C1 — Gemini spoken-line generator for the humanizer.

Situation in → SPOKEN Telugu out. The model GENERATES what a real Hyderabad
receptionist would say (natural urban Tenglish, English loanwords in Telugu
script per RULE 6), it does NOT translate. Generation is conditioned on the
example bank (few-shot) so it matches Vinay's reviewed taste. No medical advice
(RULE 7).

Telugu is only ever produced by Gemini here — never composed by the assistant.
"""
from __future__ import annotations

import json
import time

import structlog

logger = structlog.get_logger()

DEFAULT_MODEL = "gemini-2.5-flash"

_SYSTEM = """You are a real, warm clinic receptionist in Hyderabad. For each situation, write EXACTLY what you would naturally SAY out loud on the phone — generate real spoken speech, do NOT translate from English.

Speak like real urban Telugu receptionists: mostly Telugu, with English loanwords mixed in ONLY where real people genuinely use English (e.g. అపాయింట్‌మెంట్, టైం, బుక్, ఓకే, సారీ, ఫోన్, నంబర్, డాక్టర్, కన్ఫర్మ్). Do NOT turn ordinary Telugu words into English (keep నమస్తే, సహాయం, అవును, చెప్పండి, మంచిది). Sound like a person, not a Telugu-script English sentence.

HARD RULES:
- TELUGU SCRIPT ONLY. English loanwords written in Telugu script (టైం, not "time"). Never romanized.
- Keep placeholders exactly: {clinic} {issue} {doctor} {time} {date} {name}.
- Polite register: మీరు, the -అండి suffix, గారు for names.
- NO medical advice/diagnosis — only book and relay.
- Short, warm, natural spoken lines.
- Return ONLY valid JSON: the same keys as the situations, one spoken Telugu string each."""


def build_prompt(situations: dict[str, str], examples: dict[str, list[str]] | None = None) -> str:
    """Pure: assemble the Gemini prompt. ``examples`` (situation_key -> approved
    lines) are injected as few-shot guidance so the model matches reviewed taste."""
    parts = [_SYSTEM]
    examples = examples or {}
    fewshot = {k: v for k, v in examples.items() if v}
    if fewshot:
        parts.append(
            "\nHere are APPROVED example lines (match this style/register exactly):\n"
            + json.dumps(fewshot, ensure_ascii=False, indent=2)
        )
    parts.append(
        "\nSituations (JSON, key -> what is happening). Return JSON with the SAME keys:\n"
        + json.dumps(situations, ensure_ascii=False, indent=2)
    )
    return "\n".join(parts)


def _client():
    from google import genai

    from backend.config import settings

    return genai.Client(api_key=settings.gemini_api_key)


def _parse(text: str) -> dict:
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text)


def generate_lines(
    situations: dict[str, str],
    *,
    bank=None,
    client=None,
    model: str = DEFAULT_MODEL,
    retries: int = 4,
) -> dict[str, str]:
    """Generate spoken Telugu lines for ``situations``. Pulls few-shot examples
    from ``bank`` (an ExampleBank) when given. Retries on transient Gemini 503."""
    examples = None
    if bank is not None:
        examples = {k: [e["line"] for e in bank.examples_for(k)] for k in situations}
    prompt = build_prompt(situations, examples)
    client = client or _client()

    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            resp = client.models.generate_content(model=model, contents=prompt)
            return _parse(resp.text)
        except Exception as e:  # noqa: BLE001 — Gemini 503/parse, retry
            last_err = e
            logger.warning("te_gen_attempt_failed", attempt=attempt + 1, error=str(e)[:120])
            time.sleep(min(2 ** attempt, 8))
    raise RuntimeError(f"te_gen failed after {retries} attempts: {last_err}")

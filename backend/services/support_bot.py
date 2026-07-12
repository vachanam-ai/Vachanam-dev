"""Support chatbot — Gemini 2.5-flash-lite grounded on the support KB.

RULE 1: product questions only. NO tool access, NO clinic-data read. The
in-app variant may know the caller's plan (from the JWT) to answer "what's in
my plan", but never anything patient-level.
RULE 8: any LLM failure returns a safe refusal (answered=False), never raises.
No judge/sim rewrite loop (memory feedback-no-auto-prompt-tuning) — fixed prompt.
"""
from __future__ import annotations

import json

import structlog

from backend.config import settings
from backend.services import support_kb

logger = structlog.get_logger()

_FALLBACK = (
    "I'm not fully sure about that one — I've logged it so our team can help. "
    "You can also email support@vachanam.in and we'll get back to you."
)

_SYSTEM = (
    "You are Vachanam's support assistant for Indian clinics. For PRODUCT "
    "questions, answer ONLY from the KNOWLEDGE BASE below. If the knowledge "
    "base does not cover a product question, say you are not sure and that the "
    "team will follow up — do NOT invent pricing, features, or any medical "
    "advice. Greetings and small talk (hi, hello, thanks, bye, how are you) "
    "are NOT product questions: reply warmly in one short sentence, invite "
    "their question, and set answered to true — never escalate a greeting to "
    "the team. Keep it to 1-3 short sentences, plain text, no markdown "
    'symbols. Reply as JSON: {{"answer": string, "answered": boolean}} where '
    "answered is false ONLY when a product question is not covered by the "
    "knowledge base.\n\n"
    "KNOWLEDGE BASE:\n{kb}\n"
)


async def _call_gemini(prompt: str) -> str:
    """Isolated so tests swap it out. Async client (same loop as FastAPI)."""
    from google import genai
    from google.genai import types as genai_types

    client = genai.Client(api_key=settings.gemini_api_key)
    resp = await client.aio.models.generate_content(
        model="gemini-2.5-flash-lite",
        contents=prompt,
        config=genai_types.GenerateContentConfig(
            thinking_config=genai_types.ThinkingConfig(thinking_budget=0),
            response_mime_type="application/json",
            temperature=0,
            max_output_tokens=400,
        ),
    )
    return resp.text or "{}"


async def answer(question: str, history: list[dict], audience: str,
                 plan: str | None = None) -> dict:
    kb = support_kb.kb_text(audience if audience in ("public", "clinic") else "public")
    plan_line = f"\nThe user's current plan is: {plan}." if plan else ""
    convo = "".join(
        f"\n{h.get('role', 'user')}: {h.get('content', '')}" for h in history[-20:]
    )
    prompt = _SYSTEM.format(kb=kb) + plan_line + convo + f"\nuser: {question}\n"
    try:
        raw = await _call_gemini(prompt)
        data = json.loads(raw)
        ans = (data.get("answer") or "").strip()
        answered = bool(data.get("answered")) and bool(ans)
        if not ans:
            return {"answer": _FALLBACK, "answered": False}
        return {"answer": ans, "answered": answered}
    except Exception as exc:  # noqa: BLE001 — RULE 8: never break the chat
        logger.warning("support_bot_failed", error=str(exc))
        return {"answer": _FALLBACK, "answered": False}

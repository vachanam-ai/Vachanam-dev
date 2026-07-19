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

# The knowledge document is the STABLE PREFIX (provider-side implicit prompt
# caching discounts it); per-request parts (plan, history, question) come after.
_SYSTEM = (
    "KNOWLEDGE DOCUMENT (your ONLY source of truth about Vachanam):\n"
    "{kb}\n\n"
    "You are Vachanam's support assistant for Indian clinics. Answer in your "
    "own words, naturally and helpfully, using ONLY facts from the knowledge "
    "document above — you may combine and rephrase them freely, but never add "
    "facts, prices, features, or promises that are not in it.\n"
    "STRICT BOUNDARY: if the user asks something the document does not cover "
    "(other products, integrations not listed, account-specific data, "
    "requests for legal ADVICE, medical questions), do NOT attempt an answer "
    "— briefly say the support team will take it from here, and set answered "
    "to false so the ticket is forwarded to them.\n"
    "Privacy, data security, DPDP compliance, encryption, retention, breach "
    "handling and data deletion ARE covered by the document — answer these "
    "confidently from it (#420: clinics ask these as basic due diligence; "
    "'not sure' here loses the clinic). Point to vachanam.in/privacy, "
    "/data-handling or /dpa for the full text when useful.\n"
    "NEVER give medical advice of any kind.\n"
    "OFF-TOPIC (#420): for questions with no connection to Vachanam or "
    "running a clinic — coding/programming help, homework, general "
    "knowledge, news, jokes, other companies' products, personal advice — "
    "do NOT answer the question and do NOT forward it: reply in one polite "
    "sentence that you only help with Vachanam and clinic topics, invite a "
    "Vachanam question, and set answered to true (no human follow-up "
    "needed).\n"
    "Greetings and small talk (hi, hello, thanks, bye) are fine: reply warmly "
    "in one short sentence, invite their question, answered = true.\n"
    "Style: 1-4 short sentences, plain text, no markdown symbols, no lists "
    "unless the user asks for options. Currency in rupees as written in the "
    "document.\n"
    'Reply as JSON: {{"answer": string, "answered": boolean}} — answered is '
    "false ONLY when you are declining because the document does not cover it."
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
    # One end-to-end knowledge document for everyone (2026-07-12) — nothing in
    # it is clinic-confidential, and one stable prefix maximises prompt-cache
    # hits. `audience` kept in the signature for compatibility/telemetry.
    kb = support_kb.knowledge_text()
    plan_line = f"\nThe user's current plan is: {plan}." if plan else ""
    convo = "".join(
        f"\n{h.get('role', 'user')}: {h.get('content', '')}" for h in history[-20:]
    )
    prompt = _SYSTEM.format(kb=kb) + plan_line + convo + f"\nuser: {question}\n"
    try:
        # Through the resilience guard: a broken Gemini dependency (missing
        # package, bad key, outage) now shows on /admin/resilience as the
        # 'gemini_support_bot' breaker instead of hiding behind the fallback
        # for days (#330 — prod ImportError went unnoticed).
        from backend.services.resilience import guard

        raw = await guard("gemini_support_bot", lambda: _call_gemini(prompt),
                          timeout=25, retries=0)
        data = json.loads(raw)
        ans = (data.get("answer") or "").strip()
        answered = bool(data.get("answered")) and bool(ans)
        if not ans:
            return {"answer": _FALLBACK, "answered": False}
        return {"answer": ans, "answered": answered}
    except Exception as exc:  # noqa: BLE001 — RULE 8: never break the chat
        logger.warning("support_bot_failed", error=str(exc))
        return {"answer": _FALLBACK, "answered": False}

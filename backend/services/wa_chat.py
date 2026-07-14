"""WhatsApp free-text handler — Gemini intent routing (spec 2026-07-13, T7).

A patient typed free text to the clinic's WhatsApp. Gemini classifies the
intent; deterministic code acts on it:

    reschedule | cancel → the T6 clinic-callback flow on their upcoming
                          booking (never a fabricated change)
    location            → clinic address + maps link
    faq                 → answer STRICTLY from the clinic's own FAQ rows
    out_of_scope        → tap-to-call the clinic (new bookings, medical
                          anything, complaints — RULE 7: no medical judgment,
                          the AI books/informs only)

24h-window discipline: this only ever runs as a REPLY to an inbound message,
so every send here is inside Meta's free service window by construction.
Gemini failure or unparseable output → static call-us line (RULE 8).
RULE 9: the patient's text goes to Gemini for classification but is never
logged or mailed.
"""
from __future__ import annotations

import json

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.schema import Branch, Patient, Token
from backend.services import wa_actions, wa_service, wa_templates
from backend.services.resilience import guard
from backend.services.support_bot import _call_gemini

logger = structlog.get_logger()

_PROMPT = (
    "You classify ONE WhatsApp message a patient sent to an Indian clinic's "
    "assistant. You have NO medical role: never give medical advice, "
    "diagnoses, or urgency judgments — the assistant only books appointments "
    "and shares clinic information (hard rule).\n"
    "Clinic FAQ (the ONLY knowledge you may answer from):\n{faq}\n\n"
    "Patient message: {text}\n\n"
    "Intents:\n"
    "- reschedule: wants to move an existing appointment\n"
    "- cancel: wants to cancel an existing appointment\n"
    "- location: asks where the clinic is / directions\n"
    "- faq: answerable strictly from the FAQ above\n"
    "- out_of_scope: anything else — NEW bookings, medical questions, "
    "prices not in the FAQ, complaints, emergencies\n\n"
    'Reply as JSON: {{"intent": string, "answer": string}} — answer is the '
    "short reply text ONLY for intent=faq (plain text, max 3 sentences, same "
    "language as the patient's message); empty otherwise."
)


def _faq_text(branch: Branch) -> str:
    rows = branch.faq or []
    if not rows:
        return "(clinic has not provided any FAQ)"
    return "\n".join(
        f"Q: {r.get('q', '')}\nA: {r.get('a', '')}" for r in rows[:20]
    )


async def _upcoming_token_id(db: AsyncSession, branch: Branch, sender: str) -> str | None:
    """Sender's next confirmed booking at THIS branch (RULE 1 scoped).
    Meta sends numbers without '+' (919000000042); patients are stored E.164 —
    match on the last 10 digits."""
    last10 = wa_actions._last10(sender)
    if len(last10) < 10:
        return None
    from datetime import datetime
    from zoneinfo import ZoneInfo

    today = datetime.now(ZoneInfo(branch.timezone or "Asia/Kolkata")).date()
    token = (
        await db.execute(
            select(Token)
            .join(Patient, Patient.id == Token.patient_id)
            .where(
                Token.branch_id == branch.id,  # RULE 1
                Token.status == "confirmed",
                Token.date >= today,  # audit #7: never a stale past booking
                Patient.phone.like(f"%{last10}"),
            )
            .order_by(Token.date)
        )
    ).scalars().first()
    return str(token.id) if token else None


async def handle_text(db: AsyncSession, branch: Branch, sender: str, text: str) -> None:
    text = (text or "").strip()
    if not text:
        return
    try:
        prompt = _PROMPT.format(faq=_faq_text(branch), text=text[:500])
        raw = await guard("gemini_wa_chat", lambda: _call_gemini(prompt), timeout=12)
        data = json.loads(raw)
        intent = (data.get("intent") or "").strip()
    except Exception as e:  # noqa: BLE001 — RULE 8: static fallback, no dead end
        logger.warning("wa_chat_gemini_failed", error=str(e)[:150])
        await wa_actions.reply_call_us(branch, sender)
        return

    logger.info("wa_chat_intent", intent=intent, branch_id=str(branch.id))

    if intent in ("reschedule", "cancel"):
        token_id = await _upcoming_token_id(db, branch, sender)
        if token_id:
            await wa_actions.handle_change_request(
                db, branch, sender, token_id, want_cancel=(intent == "cancel")
            )
        else:
            await wa_actions.reply_call_us(branch, sender)
    elif intent == "location":
        link = wa_templates.maps_link(branch.address)
        line = (
            f"{branch.name}: {branch.address}\n{link}"
            if branch.address else "Please call us for directions."
        )
        await wa_service.send_text(branch, sender, line)
    elif intent == "faq" and (data.get("answer") or "").strip():
        await wa_service.send_text(branch, sender, data["answer"].strip()[:900])
    else:
        number = branch.clinic_phone or branch.did_number or ""
        line = (
            f"For bookings and anything else, please call us — the phone "
            f"assistant can help right away: {number}"
            if number else "Please call the clinic — the phone assistant can help."
        )
        await wa_service.send_text(branch, sender, line)

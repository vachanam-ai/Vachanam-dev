"""WhatsApp inbound button actions (spec 2026-07-13, plan T6 — day-1 scope).

Button-id grammar (set by wa_templates, dispatched by the T5 webhook):
    rate:{token_id}:{1-5}   → store Rating; score<=2 alerts the owner
    rs:{token_id}           → clinic-callback flow (PatientMessage) — see below
    cx:{token_id}           → same
    slot:...                → reserved for T6b (self-serve reschedule)

Day-1 reschedule/cancel deliberately do NOT write bookings: the atomic
reschedule lives inside the voice agent class today; duplicating it here
would be a fresh RULE 2/3 surface. Instead the tap creates a PatientMessage
("wants to reschedule booking …") that lands on the Dashboard Messages card
(the #349 loop the clinic already works), and the patient is told the clinic
will call — plus a tap-to-call link. T6b upgrades this to slot-pick self-serve
after _do_reschedule is extracted into a shared service.

RULE 1: every token lookup is branch-scoped AND phone-matched — a smuggled
token_id in a crafted payload gets a generic reply, never data.
RULE 9: the low-score alert email carries score + last4 only.
"""
from __future__ import annotations

from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.schema import (
    Branch, Patient, PatientMessage, Rating, Token,
)
from backend.services import wa_service

logger = structlog.get_logger()


def _last10(phone: str) -> str:
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    return digits[-10:]


async def _owned_token(
    db: AsyncSession, branch: Branch, sender: str, token_id: str
) -> Token | None:
    """Branch-scoped token whose patient's phone matches the sender."""
    try:
        tid = UUID(token_id)
    except (ValueError, TypeError):
        return None
    row = (
        await db.execute(
            select(Token, Patient)
            .join(Patient, Patient.id == Token.patient_id)
            .where(Token.id == tid, Token.branch_id == branch.id)  # RULE 1
        )
    ).first()
    if row is None:
        return None
    token, patient = row
    if _last10(patient.phone or "") != _last10(sender):
        logger.warning(
            "wa_token_phone_mismatch", branch_id=str(branch.id),
            token_id=token_id[:8],
        )
        return None
    return token


async def reply_call_us(branch: Branch, sender: str) -> None:
    """Static no-dead-end reply (RULE 8)."""
    number = branch.clinic_phone or branch.did_number or ""
    line = (
        f"Sorry, something went wrong. Please call us at {number}."
        if number else "Sorry, something went wrong. Please call the clinic."
    )
    await wa_service.send_text(branch, sender, line)


async def dispatch_button(
    db: AsyncSession, branch: Branch, plan: str, sender: str, payload: str
) -> None:
    """Route a quick-reply payload by grammar prefix. Unknown → call-us."""
    parts = (payload or "").split(":")
    kind = parts[0] if parts else ""
    if kind == "rate" and len(parts) == 3:
        await handle_rating(db, branch, sender, parts[1], parts[2])
    elif kind in ("rs", "cx") and len(parts) == 2:
        await handle_change_request(db, branch, sender, parts[1], want_cancel=(kind == "cx"))
    else:
        logger.info("wa_unknown_button", payload=payload[:40])
        await reply_call_us(branch, sender)


async def handle_rating(
    db: AsyncSession, branch: Branch, sender: str, token_id: str, score_s: str
) -> None:
    token = await _owned_token(db, branch, sender, token_id)
    try:
        score = int(score_s)
    except ValueError:
        score = 0
    if token is None or not 1 <= score <= 5:
        await reply_call_us(branch, sender)
        return
    existing = (
        await db.execute(select(Rating).where(Rating.token_id == token.id))
    ).scalar_one_or_none()
    if existing is None:
        from sqlalchemy.exc import IntegrityError

        try:
            db.add(Rating(
                branch_id=branch.id, token_id=token.id,
                patient_id=token.patient_id, score=score,
            ))
            await db.commit()
        except IntegrityError:
            # Audit #10: concurrent double-tap — unique(token_id) won the
            # race for the other insert. Idempotent thank-you, no error path.
            await db.rollback()
        else:
            logger.info("wa_rating_stored", branch_id=str(branch.id), score=score)
            if score <= 2:
                await _notify_low_score(branch, sender, score)
    await wa_service.send_text(
        branch, sender, "Thank you for your feedback! 🙏"
    )


async def _notify_low_score(branch: Branch, sender: str, score: int) -> None:
    """Owner email on a 1-2 star rating. RULE 9: score + last4 only. Own
    session + fully guarded — feedback must never break the webhook."""
    try:
        from backend.services.support_email import notify_owner_low_rating

        await notify_owner_low_rating(branch.id, score, sender[-4:] if sender else "")
    except Exception as e:  # noqa: BLE001
        logger.warning("wa_low_score_notify_failed", error=str(e)[:120])


async def handle_change_request(
    db: AsyncSession, branch: Branch, sender: str, token_id: str,
    *, want_cancel: bool,
) -> None:
    """Day-1 reschedule/cancel: verified booking → PatientMessage on the
    Dashboard (clinic calls back) + honest reply with tap-to-call. Never
    claims the booking was changed (nothing was written)."""
    token = await _owned_token(db, branch, sender, token_id)
    if token is None or token.status != "confirmed":
        await reply_call_us(branch, sender)
        return
    what = "cancel" if want_cancel else "reschedule"
    when = (
        f"{token.date.isoformat()} {token.appointment_time.strftime('%H:%M')}"
        if token.appointment_time else f"{token.date.isoformat()} token {token.token_number}"
    )
    db.add(PatientMessage(
        branch_id=branch.id,
        patient_id=token.patient_id,
        caller_phone=sender,
        message=f"[WhatsApp] Wants to {what} the booking on {when}.",
        urgent=False,
    ))
    await db.commit()
    number = branch.clinic_phone or branch.did_number or ""
    call_bit = f" You can also call us right away: {number}" if number else ""
    await wa_service.send_text(
        branch, sender,
        f"Got it — the clinic will call you shortly to {what} your "
        f"appointment.{call_bit}",
    )
    logger.info(
        "wa_change_request", what=what, branch_id=str(branch.id),
        token_id=str(token.id)[:8],
    )

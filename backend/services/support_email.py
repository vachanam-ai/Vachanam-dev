"""Support email notifications via Resend. RULE 8: every send is best-effort —
a Resend outage logs and returns, it NEVER raises or blocks a ticket/message
write. RULE 9: subjects/bodies here are support text (no patient PII by policy);
we still keep them short and never log the body.

Volume policy (Vinay 2026-07-12, Resend quota): the team gets exactly ONE mail
per new ticket that needs a human (notify_new_ticket). No per-reply mail to the
team. Clinics get a mail only when staff reply or resolve. Everything is sent
FROM support@vachanam.in and team mail lands at support@vachanam.in.
"""
from __future__ import annotations

import httpx
import structlog

from backend.config import settings

logger = structlog.get_logger()


async def _send(to: str, subject: str, text: str) -> None:
    """Fire one email FROM the support address. Best-effort — routed through the
    resilience guard so a slow/down Resend trips the 'resend_email' circuit
    breaker (visible on /admin/resilience) instead of silently eating threads.
    fallback=None ⇒ never raises (RULE 8)."""
    if not settings.resend_api_key or not to:
        return
    from backend.services.resilience import guard

    async def _post():
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {settings.resend_api_key}"},
                json={"from": settings.support_from, "to": [to],
                      "subject": subject, "text": text},
            )
            r.raise_for_status()  # a 4xx/5xx is a dependency failure the breaker must see

    result = await guard("resend_email", _post, timeout=12, retries=1, fallback=False)
    if result is False:
        logger.warning("support_email_failed", to_last4=to[-4:])


def _app_link(path: str) -> str:
    return f"{settings.frontend_url.rstrip('/')}{path}"


async def notify_new_ticket(ticket_id, subject: str, from_email: str) -> None:
    """The ONLY routine mail to the team — one per new ticket needing a human."""
    await _send(
        settings.support_email,
        f"New support ticket: {subject[:80]}",
        f"A new support ticket needs a reply (from {from_email}).\n\n"
        f"Open the support dashboard: {_app_link('/support-admin')}\n"
        f"Ticket id: {ticket_id}",
    )


async def notify_staff_reply(to_email: str, subject: str) -> None:
    """To the CLINIC when the team replies. Sent from support@."""
    await _send(
        to_email,
        f"Re: {subject[:80]} — Vachanam support",
        "Our support team replied to your ticket. Open Vachanam and go to "
        f"Support to read and reply:\n\n{_app_link('/tickets')}\n\n— Vachanam Support",
    )


async def notify_clinic_message(
    branch_id, caller_name: str | None = None, caller_last4: str | None = None
) -> None:
    """URGENT caller message (#349) → ONE mail to the clinic owner pointing at
    the dashboard. RULE 9: the message TEXT never rides the email (it can
    contain health details) — the mail says WHO is waiting (name + last-4,
    the same identity scope as calendar events) but not what they said.
    Opens its own short session (called from the voice agent mid-call)."""
    import backend.database as dbm
    from sqlalchemy import select

    from backend.models.schema import Branch, Organization

    async with dbm.AsyncSessionLocal() as db:
        row = (
            await db.execute(
                select(Organization.owner_email, Branch.name)
                .join(Branch, Branch.org_id == Organization.id)
                .where(Branch.id == branch_id)
            )
        ).first()
    if not row or not row[0]:
        return
    who = caller_name or "A caller"
    if caller_last4:
        who += f" (…{caller_last4})"
    await _send(
        row[0],
        f"Urgent: {who} left a message for {row[1]}",
        f"{who} just left an URGENT message for your clinic and expects a "
        "call back.\n\nRead it on your dashboard (Messages):\n"
        f"{_app_link('/dashboard')}\n\n— Vachanam",
    )


async def notify_owner_low_rating(branch_id, score: int, last4: str) -> None:
    """Owner alert on a 1-2 star WhatsApp rating (WA T6). RULE 9: score +
    last-4 only — ratings carry no text at all by design. Own short session,
    fully guarded by the caller."""
    import backend.database as dbm
    from sqlalchemy import select

    from backend.models.schema import Branch, Organization

    async with dbm.AsyncSessionLocal() as db:
        row = (
            await db.execute(
                select(Organization.owner_email, Branch.name)
                .join(Branch, Branch.org_id == Organization.id)
                .where(Branch.id == branch_id)
            )
        ).first()
    if not row or not row[0]:
        return
    await _send(
        row[0],
        f"Low rating: {score}/5 after a visit at {row[1]}",
        f"A patient (…{last4}) rated their visit {score}/5 on WhatsApp.\n\n"
        "A quick call from the clinic often turns this around.\n\n— Vachanam",
    )


async def notify_resolved(to_email: str, subject: str) -> None:
    """To the CLINIC when their ticket is resolved. Sent from support@."""
    await _send(
        to_email,
        f"Resolved: {subject[:80]} — Vachanam support",
        "Our team marked your support ticket as resolved. If it's sorted, you "
        "can rate the help in the app; if not, just reply to reopen it:\n\n"
        f"{_app_link('/tickets')}\n\n— Vachanam Support",
    )

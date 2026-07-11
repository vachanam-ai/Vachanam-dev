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
    """Fire one email FROM the support address. Swallows every error (RULE 8)."""
    if not settings.resend_api_key or not to:
        return
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            await c.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {settings.resend_api_key}"},
                json={"from": settings.support_from, "to": [to],
                      "subject": subject, "text": text},
            )
    except Exception as exc:  # noqa: BLE001 — email must never break support flow
        logger.warning("support_email_failed", to_last4=to[-4:], error=str(exc))


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


async def notify_resolved(to_email: str, subject: str) -> None:
    """To the CLINIC when their ticket is resolved. Sent from support@."""
    await _send(
        to_email,
        f"Resolved: {subject[:80]} — Vachanam support",
        "Our team marked your support ticket as resolved. If it's sorted, you "
        "can rate the help in the app; if not, just reply to reopen it:\n\n"
        f"{_app_link('/tickets')}\n\n— Vachanam Support",
    )

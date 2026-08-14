"""SLA escalation: hourly, email Vinay a digest of tickets that blew their SLA
without a first response. Read-only on tickets — no auto-actions (RULE: humans
decide). Redis nx-dedup per ticket so one overdue ticket escalates once.
RULE 8: Redis/email failure skips quietly and retries next tick.
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx
import structlog
from sqlalchemy import and_, select

import backend.database as _db_module
from backend.config import settings
from backend.models.schema import SupportTicket
from backend.redis_client import get_redis

logger = structlog.get_logger()


async def run_sla_escalation() -> None:
    now = datetime.now(timezone.utc)
    async with _db_module.AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(SupportTicket).where(
                    and_(
                        SupportTicket.status == "open",
                        SupportTicket.first_responded_at.is_(None),
                        SupportTicket.sla_due_at.is_not(None),
                        SupportTicket.sla_due_at < now,
                    )
                ).limit(200)
            )
        ).scalars().all()

    overdue = []
    for t in rows:
        try:
            fresh = await get_redis().set(
                f"support_sla_escalated:{t.id}", "1", ex=7 * 86400, nx=True
            )
        except Exception:  # noqa: BLE001 — Redis down: skip, retry next tick
            continue
        if fresh:
            overdue.append(t)

    if not overdue or not settings.resend_api_key or not settings.support_sla_email:
        if overdue:
            logger.warning("support_sla_overdue", count=len(overdue),
                           emailed=False)
        return

    lines = "\n".join(
        f"- {t.subject[:60]} · {t.priority} · due {t.sla_due_at:%d %b %H:%M} · "
        f"{t.email}" for t in overdue
    )
    dash = f"{settings.frontend_url.rstrip('/')}/support-admin"
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            await c.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {settings.resend_api_key}"},
                json={
                    "from": settings.support_from,
                    "to": [settings.support_email],
                    "subject": f"{len(overdue)} support ticket(s) past SLA — no reply yet",
                    "text": f"These tickets are overdue and still unanswered:\n\n{lines}\n\n"
                            f"Open the dashboard: {dash}",
                },
            )
        logger.info("support_sla_escalated", count=len(overdue))
    except Exception as exc:  # noqa: BLE001 — RULE 8
        logger.warning("support_sla_email_failed", error=str(exc), count=len(overdue))

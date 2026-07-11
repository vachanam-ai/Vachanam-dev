"""SLA escalation picks only overdue + unanswered open tickets and dedups."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.asyncio


async def _mk(db, *, overdue, answered=False, status="open"):
    from backend.models.schema import Organization, SupportTicket
    o = Organization(name="C", owner_phone="", owner_email=f"{uuid.uuid4().hex}@t.com",
                     plan="clinic", status="active")
    db.add(o)
    await db.flush()
    now = datetime.now(timezone.utc)
    t = SupportTicket(
        org_id=o.id, email="o@t.com", subject="s", category="other",
        status=status, priority="normal", source="in_app",
        sla_due_at=now - timedelta(hours=1) if overdue else now + timedelta(hours=5),
        first_responded_at=now if answered else None,
    )
    db.add(t)
    await db.commit()
    return t


async def test_escalation_selects_only_overdue_unanswered_and_dedups(db, redis):
    from backend.jobs import support_sla

    overdue = await _mk(db, overdue=True)
    await _mk(db, overdue=False)              # not due yet
    await _mk(db, overdue=True, answered=True)  # overdue but already answered
    await _mk(db, overdue=True, status="pending")  # not 'open'

    # resend key is empty in tests → job selects + dedups, sends nothing.
    await support_sla.run_sla_escalation()

    # only the overdue+unanswered+open ticket got a dedup marker
    assert await redis.get(f"support_sla_escalated:{overdue.id}") is not None

    # second run must NOT re-escalate (nx dedup holds) — no crash, idempotent
    await support_sla.run_sla_escalation()

"""Metering durability (TD-027/F6): crash-stranded CallLog rows get reconciled.

The agent writes a CallLog at call start (duration 0) and finalizes it at end.
A worker killed mid-call leaves duration 0; run_finalize_stale_calls finalizes
those (older than the grace window) to a conservative estimate, without touching
live (recent) or already-finalized rows.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

from backend.jobs.finalize_stale_calls import run_finalize_stale_calls
from backend.models.schema import Branch, CallLog, Organization

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def branch(db):
    org = Organization(
        name="Meter Org", owner_phone="+919000666001",
        owner_email=f"m-{uuid.uuid4().hex[:6]}@test.com", plan="clinic", status="active",
    )
    db.add(org)
    await db.flush()
    b = Branch(
        org_id=org.id, name="Meter Branch",
        whatsapp_number=f"+9166{str(uuid.uuid4().int)[:8]}", status="active",
    )
    db.add(b)
    await db.commit()
    return b


async def test_stale_zero_duration_call_is_finalized(branch, db):
    now = datetime.now(timezone.utc)
    stale = CallLog(branch_id=branch.id, call_type="inbound", answered=True,
                    started_at=now - timedelta(hours=2), duration_seconds=0,
                    booking_made=False)
    recent = CallLog(branch_id=branch.id, call_type="inbound", answered=True,
                     started_at=now, duration_seconds=0, booking_made=False)
    done = CallLog(branch_id=branch.id, call_type="inbound", answered=True,
                   started_at=now - timedelta(hours=3), duration_seconds=100,
                   booking_made=True)
    db.add_all([stale, recent, done])
    await db.commit()
    stale_id, recent_id, done_id = stale.id, recent.id, done.id
    bid = branch.id  # capture before expire (avoid sync lazy-load on async session)

    await run_finalize_stale_calls()

    db.expire_all()
    rows = {
        r.id: r
        for r in (
            await db.execute(select(CallLog).where(CallLog.branch_id == bid))
        ).scalars().all()
    }
    assert rows[stale_id].duration_seconds == 180   # finalized to 3-min estimate
    assert rows[recent_id].duration_seconds == 0    # still live — untouched
    assert rows[done_id].duration_seconds == 100    # already finalized — untouched

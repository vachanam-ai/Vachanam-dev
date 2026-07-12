"""#340: anniversary billing — the renewal loop that didn't exist.

Before this, ONE Razorpay payment kept an org active forever: no cycle end was
enforced, no renewal was requested. Now:
- activation starts the 30-day cycle the day they pay;
- a renewal paid EARLY starts where the current cycle ends (contiguous, no
  paid days lost); paid late, it starts today;
- run_billing_renewal pauses an active org 3 days after an unpaid cycle end,
  leaves in-grace and cycle-less orgs alone.
"""
import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from backend.models.schema import BillingCycle, Organization
from backend.routers.payments import activate_subscription

pytestmark = pytest.mark.asyncio


async def _org(db, status="active", plan="solo"):
    org = Organization(
        name="Renewal Clinic", owner_phone="+919000000060",
        owner_email=f"renew-{uuid.uuid4().hex[:8]}@clinic.in",
        plan=plan, status=status,
    )
    db.add(org)
    await db.commit()
    await db.refresh(org)
    return org


async def _cycles(db, org):
    return (
        await db.execute(
            select(BillingCycle).where(BillingCycle.org_id == org.id)
            .order_by(BillingCycle.cycle_start)
        )
    ).scalars().all()


async def test_first_activation_starts_cycle_today(db):
    org = await _org(db, status="trial")
    res = await activate_subscription(db, str(org.id), "solo", f"pay_{uuid.uuid4().hex[:10]}")
    assert res == "activated"
    (c,) = await _cycles(db, org)
    assert c.cycle_start == date.today()
    assert c.cycle_end == date.today() + timedelta(days=30)
    await db.refresh(org)
    assert org.status == "active"


async def test_early_renewal_is_contiguous(db):
    org = await _org(db, status="trial")
    await activate_subscription(db, str(org.id), "solo", f"pay_{uuid.uuid4().hex[:10]}")
    # renew 28 days early (2 days into the cycle it's day 2, end is day 30)
    res = await activate_subscription(db, str(org.id), "solo", f"pay_{uuid.uuid4().hex[:10]}")
    assert res == "activated"
    c1, c2 = await _cycles(db, org)
    assert c2.cycle_start == c1.cycle_end  # no paid days lost
    assert c2.cycle_end == c1.cycle_end + timedelta(days=30)


async def test_late_renewal_starts_today(db):
    org = await _org(db, status="paused")
    old_end = date.today() - timedelta(days=10)
    db.add(BillingCycle(
        org_id=org.id, cycle_start=old_end - timedelta(days=30), cycle_end=old_end,
        plan="solo", base_amount=5999, included_minutes=700, minutes_used=700,
        overage_minutes=0, overage_rate=5, overage_amount=0,
        status="paid", razorpay_payment_id=f"pay_{uuid.uuid4().hex[:10]}",
    ))
    await db.commit()
    await activate_subscription(db, str(org.id), "solo", f"pay_{uuid.uuid4().hex[:10]}")
    _, c2 = await _cycles(db, org)
    assert c2.cycle_start == date.today()  # the gap wasn't served — no backdating
    await db.refresh(org)
    assert org.status == "active"


async def test_renewal_job_pauses_after_grace(db):
    import backend.jobs.trial_pause as job

    org = await _org(db, status="active")
    end = date.today() - timedelta(days=4)  # 4 days past end > 3-day grace
    db.add(BillingCycle(
        org_id=org.id, cycle_start=end - timedelta(days=30), cycle_end=end,
        plan="solo", base_amount=5999, included_minutes=700, minutes_used=0,
        overage_minutes=0, overage_rate=5, overage_amount=0,
        status="paid", razorpay_payment_id=f"pay_{uuid.uuid4().hex[:10]}",
    ))
    await db.commit()

    await job.run_billing_renewal(today=date.today())

    await db.refresh(org)
    assert org.status == "paused"


async def test_renewal_job_respects_grace_and_cycleless_orgs(db):
    import backend.jobs.trial_pause as job

    in_grace = await _org(db, status="active")
    end = date.today() - timedelta(days=2)  # inside 3-day grace
    db.add(BillingCycle(
        org_id=in_grace.id, cycle_start=end - timedelta(days=30), cycle_end=end,
        plan="solo", base_amount=5999, included_minutes=700, minutes_used=0,
        overage_minutes=0, overage_rate=5, overage_amount=0,
        status="paid", razorpay_payment_id=f"pay_{uuid.uuid4().hex[:10]}",
    ))
    no_cycle = await _org(db, status="active")  # admin-activated, never billed
    await db.commit()

    await job.run_billing_renewal(today=date.today())

    await db.refresh(in_grace)
    await db.refresh(no_cycle)
    assert in_grace.status == "active"
    assert no_cycle.status == "active"

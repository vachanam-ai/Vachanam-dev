"""Clinic self-serve plan change — ANNIVERSARY billing (#340, 2026-07-12).

A clinic's cycle starts the day they pay (not the 1st of the month). A plan
switch scheduled mid-cycle applies at the CURRENT PAID CYCLE'S end; a clinic
with no future paid cycle (trial/paused) switches immediately. Covers:
scheduling against a cycle, immediate switch without one, cancelling, RBAC,
and the apply job.
"""
import uuid
from datetime import date, timedelta

import pytest

from backend.middleware.auth_middleware import CurrentUser
from backend.models.schema import BillingCycle, Organization
from backend.routers.payments import PlanChangeRequest, change_plan
from backend.services.billing_math import next_cycle_start

pytestmark = pytest.mark.asyncio


def test_next_cycle_start_rolls_to_first_of_next_month():
    # Retained for the legacy helper (still used as a fallback elsewhere).
    assert next_cycle_start(date(2026, 6, 23)) == date(2026, 7, 1)
    assert next_cycle_start(date(2026, 6, 1)) == date(2026, 7, 1)
    assert next_cycle_start(date(2026, 12, 15)) == date(2027, 1, 1)  # year wrap


async def _seed_org(db, plan="solo", status="active"):
    org = Organization(
        name="Plan Clinic", owner_phone="+919000000050",
        owner_email=f"plan-{uuid.uuid4().hex[:8]}@realclinic.in",
        plan=plan, status=status,
    )
    db.add(org)
    await db.commit()
    await db.refresh(org)
    return org


async def _seed_cycle(db, org, end, start=None):
    bc = BillingCycle(
        org_id=org.id,
        cycle_start=start or (end - timedelta(days=30)),
        cycle_end=end,
        plan=org.plan, base_amount=5999, included_minutes=700,
        minutes_used=0, overage_minutes=0, overage_rate=5, overage_amount=0,
        status="paid", razorpay_payment_id=f"pay_{uuid.uuid4().hex[:12]}",
    )
    db.add(bc)
    await db.commit()
    return bc


def _user(org, role="org_admin"):
    return CurrentUser(
        user_id=str(uuid.uuid4()), email="o@x.in", role=role,
        org_id=str(org.id), branch_ids=[], is_admin=False, jti="j",
    )


async def test_plan_change_scheduled_for_current_cycle_end(db):
    org = await _seed_org(db, plan="solo")
    cycle_end = date.today() + timedelta(days=12)
    await _seed_cycle(db, org, end=cycle_end)
    info = await change_plan(PlanChangeRequest(plan="clinic"), _user(org), db)
    assert info.plan == "solo"  # current paid cycle untouched
    assert info.pending_plan == "clinic"
    assert info.pending_plan_effective == cycle_end.isoformat()  # anniversary, not 1st


async def test_plan_change_without_paid_cycle_applies_immediately(db):
    org = await _seed_org(db, plan="solo", status="trial")
    info = await change_plan(PlanChangeRequest(plan="clinic"), _user(org), db)
    assert info.plan == "clinic"  # nothing paid to protect
    assert info.pending_plan is None


async def test_selecting_current_plan_cancels_pending(db):
    org = await _seed_org(db, plan="solo")
    await _seed_cycle(db, org, end=date.today() + timedelta(days=10))
    await change_plan(PlanChangeRequest(plan="multi"), _user(org), db)
    info = await change_plan(PlanChangeRequest(plan="solo"), _user(org), db)
    assert info.pending_plan is None
    assert info.pending_plan_effective is None


async def test_non_admin_cannot_change_plan(db):
    org = await _seed_org(db)
    with pytest.raises(Exception) as ei:
        await change_plan(PlanChangeRequest(plan="clinic"), _user(org, role="receptionist"), db)
    assert getattr(ei.value, "status_code", None) == 403


async def test_invalid_plan_rejected(db):
    org = await _seed_org(db)
    with pytest.raises(Exception) as ei:
        await change_plan(PlanChangeRequest(plan="enterprise"), _user(org), db)
    assert getattr(ei.value, "status_code", None) == 422


async def test_apply_job_promotes_due_pending_plan(db):
    import backend.jobs.trial_pause as job

    org = await _seed_org(db, plan="solo")
    org.pending_plan = "clinic"
    org.pending_plan_effective = date(2026, 1, 1)  # already due
    await db.commit()

    await job.run_pending_plan_changes(today=date(2026, 6, 23))

    await db.refresh(org)
    assert org.plan == "clinic"
    assert org.pending_plan is None
    assert org.pending_plan_effective is None


async def test_apply_job_skips_future_pending_plan(db):
    import backend.jobs.trial_pause as job

    org = await _seed_org(db, plan="solo")
    org.pending_plan = "multi"
    org.pending_plan_effective = date(2099, 1, 1)  # far future
    await db.commit()

    await job.run_pending_plan_changes(today=date(2026, 6, 23))

    await db.refresh(org)
    assert org.plan == "solo"  # not yet applied
    assert org.pending_plan == "multi"

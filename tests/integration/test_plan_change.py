"""Clinic self-serve plan change, effective next billing cycle (new 2026-06-23).

A clinic owner schedules a switch via POST /api/plan-change; it sits in
pending_plan/pending_plan_effective (1st of next month) until run_pending_plan_changes
promotes it. Covers: effective-date math, scheduling, cancelling a pending
change, non-admin rejection, and the apply job.
"""
import uuid
from datetime import date

import pytest

from backend.middleware.auth_middleware import CurrentUser
from backend.models.schema import Organization
from backend.routers.payments import PlanChangeRequest, change_plan, get_plan
from backend.services.billing_math import next_cycle_start

pytestmark = pytest.mark.asyncio


def test_next_cycle_start_rolls_to_first_of_next_month():
    assert next_cycle_start(date(2026, 6, 23)) == date(2026, 7, 1)
    assert next_cycle_start(date(2026, 6, 1)) == date(2026, 7, 1)
    assert next_cycle_start(date(2026, 12, 15)) == date(2027, 1, 1)  # year wrap


async def _seed_org(db, plan="solo"):
    org = Organization(
        name="Plan Clinic", owner_phone="+919000000050",
        owner_email=f"plan-{uuid.uuid4().hex[:8]}@realclinic.in",
        plan=plan, status="active",
    )
    db.add(org)
    await db.commit()
    await db.refresh(org)
    return org


def _user(org, role="org_admin"):
    return CurrentUser(
        user_id=str(uuid.uuid4()), email="o@x.in", role=role,
        org_id=str(org.id), branch_ids=[], is_admin=False, jti="j",
    )


async def test_schedule_plan_change_sets_pending_for_next_cycle(db):
    org = await _seed_org(db, plan="solo")
    info = await change_plan(PlanChangeRequest(plan="clinic"), _user(org), db)
    assert info.plan == "solo"  # current plan unchanged this cycle
    assert info.pending_plan == "clinic"
    assert info.pending_plan_effective == next_cycle_start(date.today()).isoformat()


async def test_selecting_current_plan_cancels_pending(db):
    org = await _seed_org(db, plan="solo")
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

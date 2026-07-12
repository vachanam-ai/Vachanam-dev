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
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from backend.models.schema import BillingCycle, Branch, CallLog, Organization
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


async def test_renewal_charges_overage_and_gst(db, monkeypatch):
    """#341 (Vinay: '50 extra minutes → ₹250 — how is it charged?'):
    renewal order = base + overage + 18% GST, and the webhook stamps the
    closing cycle's meter."""
    from backend.middleware.auth_middleware import CurrentUser
    from backend.routers import payments as pay
    from backend.routers.payments import CreateOrderRequest, create_order

    org = await _org(db, status="active", plan="clinic")  # 1,500 min included
    branch = Branch(org_id=org.id, name="Main", whatsapp_number="+911234500000")
    db.add(branch)
    await db.flush()
    start = date.today() - timedelta(days=28)
    end = start + timedelta(days=30)
    db.add(BillingCycle(
        org_id=org.id, cycle_start=start, cycle_end=end,
        plan="clinic", base_amount=9999, included_minutes=1500, minutes_used=0,
        overage_minutes=0, overage_rate=5, overage_amount=0,
        status="paid", razorpay_payment_id=f"pay_{uuid.uuid4().hex[:10]}",
    ))
    # 1,550 minutes of calls inside the cycle window → 50 min overage
    db.add(CallLog(
        branch_id=branch.id, call_type="inbound",
        started_at=datetime(start.year, start.month, start.day, 12,
                            tzinfo=timezone.utc) + timedelta(days=1),
        duration_seconds=1550 * 60,
    ))
    await db.commit()

    captured = {}

    class _FakeOrders:
        def create(self, payload):
            captured.update(payload)
            return {"id": "order_test123", "amount": payload["amount"], "currency": "INR"}

    class _FakeClient:
        order = _FakeOrders()

    monkeypatch.setattr(pay, "_get_client", lambda: _FakeClient())
    monkeypatch.setattr(pay.settings, "razorpay_key_id", "rzp_test_x")

    user = CurrentUser(user_id=str(uuid.uuid4()), email="o@x.in", role="org_admin",
                       org_id=str(org.id), branch_ids=[], is_admin=False, jti="j")
    resp = await create_order(None, CreateOrderRequest(plan="clinic"), user, db)

    # 9,999 + 50×5 = 10,249 → +18% GST = 12,093.82 → 1,209,382 paise
    assert resp.amount == 1209382
    assert captured["notes"]["overage_minutes"] == "50"
    assert captured["notes"]["overage_amount"] == "250.0"

    # Webhook closes the meter on the old cycle and opens a contiguous one.
    res = await activate_subscription(db, str(org.id), "clinic",
                                      f"pay_{uuid.uuid4().hex[:10]}")
    assert res == "activated"
    c1, c2 = await _cycles(db, org)
    assert c1.minutes_used == 1550
    assert c1.overage_minutes == 50
    assert c1.overage_amount == 250
    assert c2.cycle_start == c1.cycle_end  # contiguous


async def test_pay_window_locked_mid_cycle(db):
    """#353 (Vinay: 'payment is accepting n number of times'): an active org
    whose cycle ends >3 days out gets a 409 — server-side, so a stale UI or
    direct API call can't stack payments."""
    from fastapi import HTTPException

    from backend.middleware.auth_middleware import CurrentUser
    from backend.routers.payments import CreateOrderRequest, create_order

    org = await _org(db, status="active", plan="solo")
    start = date.today() - timedelta(days=10)  # ends in 20 days
    db.add(BillingCycle(
        org_id=org.id, cycle_start=start, cycle_end=start + timedelta(days=30),
        plan="solo", base_amount=5999, included_minutes=700, minutes_used=0,
        overage_minutes=0, overage_rate=5, overage_amount=0,
        status="paid", razorpay_payment_id=f"pay_{uuid.uuid4().hex[:10]}",
    ))
    await db.commit()

    user = CurrentUser(user_id=str(uuid.uuid4()), email="o@x.in", role="org_admin",
                       org_id=str(org.id), branch_ids=[], is_admin=False, jti="j")
    with pytest.raises(HTTPException) as ei:
        await create_order(None, CreateOrderRequest(plan="solo"), user, db)
    assert ei.value.status_code == 409
    assert "Renewal opens 3 days" in ei.value.detail


async def test_pay_window_open_for_active_org_without_cycle(db, monkeypatch):
    """#351/#353: an admin-activated org (active, never billed) must always be
    able to pay — that state previously had NO pay path at all."""
    from backend.middleware.auth_middleware import CurrentUser
    from backend.routers import payments as pay
    from backend.routers.payments import CreateOrderRequest, create_order

    org = await _org(db, status="active", plan="solo")

    class _FakeOrders:
        def create(self, payload):
            return {"id": "order_nocycle", "amount": payload["amount"], "currency": "INR"}

    class _FakeClient:
        order = _FakeOrders()

    monkeypatch.setattr(pay, "_get_client", lambda: _FakeClient())
    monkeypatch.setattr(pay.settings, "razorpay_key_id", "rzp_test_x")

    user = CurrentUser(user_id=str(uuid.uuid4()), email="o@x.in", role="org_admin",
                       org_id=str(org.id), branch_ids=[], is_admin=False, jti="j")
    resp = await create_order(None, CreateOrderRequest(plan="solo"), user, db)
    assert resp.order_id == "order_nocycle"


async def test_plan_info_carries_last_payment_date(db):
    """#353: the Settings card shows when the org last paid."""
    from backend.routers.payments import _latest_cycle, _plan_info

    org = await _org(db, status="active", plan="solo")
    start = date.today() - timedelta(days=5)
    db.add(BillingCycle(
        org_id=org.id, cycle_start=start, cycle_end=start + timedelta(days=30),
        plan="solo", base_amount=5999, included_minutes=700, minutes_used=0,
        overage_minutes=0, overage_rate=5, overage_amount=0,
        status="paid", razorpay_payment_id=f"pay_{uuid.uuid4().hex[:10]}",
    ))
    await db.commit()

    info = _plan_info(org, await _latest_cycle(db, org.id))
    assert info.cycle_end == (start + timedelta(days=30)).isoformat()
    assert info.last_payment_date == date.today().isoformat()  # row created today


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

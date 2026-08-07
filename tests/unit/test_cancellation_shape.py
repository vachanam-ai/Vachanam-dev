"""End-of-cycle cancellation (Vinay 2026-08-07).

    "we need to add cancel option. where they can exit completely. and effect
     will take place from coming month (after their current cycle ends).
     this can happen where they decided to cancel voice plans completely and
     just include whatsapp"

Two different things, deliberately kept apart:
  - EXIT COMPLETELY      -> /api/plan-cancel, org status becomes `cancelled`
  - DROP VOICE, KEEP WA  -> /api/plan-change to `wa` (an existing plan)
Both land at the same moment: the end of the cycle already paid for.
"""
from __future__ import annotations

import inspect


def test_cancelling_never_cuts_service_mid_cycle():
    """The clinic paid for this cycle. Taking the service away before it ends
    would be keeping money for something we withdrew."""
    import backend.routers.payments as m

    src = inspect.getsource(m.cancel_subscription)
    assert "cycle_end = await _latest_cycle_end(db, org.id)" in src
    assert "if cycle_end and cycle_end > date.today():" in src
    assert "org.cancellation_effective = cycle_end" in src


def test_cancelling_with_nothing_paid_for_applies_immediately():
    """Trial / paused / lapsed: there is no paid cycle left to honour."""
    import backend.routers.payments as m

    src = inspect.getsource(m.cancel_subscription)
    assert 'org.status = "cancelled"' in src


def test_a_clinic_can_change_its_mind_while_still_paying():
    import backend.routers.payments as m

    src = inspect.getsource(m.cancel_subscription)
    assert "if not req.cancel:" in src
    assert "org.cancellation_effective = None" in src


def test_only_the_owner_can_cancel():
    import backend.routers.payments as m

    src = inspect.getsource(m.cancel_subscription)
    assert 'current_user.role != "org_admin"' in src
    assert "403" in src


def test_cancelling_clears_a_pending_plan_change():
    """Nothing left to change into."""
    import backend.routers.payments as m

    src = inspect.getsource(m.cancel_subscription)
    assert "org.pending_plan = None" in src


def test_whatsapp_only_is_a_plan_change_not_a_cancellation():
    """Dropping voice but keeping WhatsApp must NOT cancel the org — `wa` is a
    real plan, and the existing end-of-cycle rule already covers it."""
    from backend.services.billing_math import PLANS

    assert "wa" in PLANS, "the WhatsApp-only plan must exist to downgrade into"
    assert PLANS["wa"].included_minutes == 0, "it buys no voice minutes"

    import backend.routers.payments as m

    src = inspect.getsource(m.change_plan)
    assert "cancelled" not in src, "a downgrade must never cancel the org"


def test_the_daily_job_applies_a_due_cancellation_once():
    import backend.jobs.trial_pause as j

    src = inspect.getsource(j)
    assert "Organization.cancellation_effective <= today" in src
    assert 'Organization.status != "cancelled"' in src, "must be idempotent"
    assert 'org.status = "cancelled"' in src
    assert "org.cancellation_effective = None" in src


def test_the_cancellation_date_reaches_the_ui():
    import backend.routers.payments as m

    assert "cancellation_effective" in inspect.getsource(m.PlanInfo)
    assert "cancellation_effective" in inspect.getsource(m.BillingSummary)

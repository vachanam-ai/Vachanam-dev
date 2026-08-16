"""The Billing page's data contract (Vinay 2026-08-07: "this is money part").

Source-level, no DB: what matters is that the page can never disagree with the
invoice, which means the SERVER does every sum and the UI renders finished
figures.
"""
from __future__ import annotations

import inspect


def test_summary_totals_are_computed_server_side():
    """If the UI added these up itself it could drift from the real charge."""
    import backend.routers.payments as m

    src = inspect.getsource(m.billing_summary)
    assert "autopay_subtotal = base_next + addon_amt" in src
    assert "subtotal = autopay_subtotal + over_amt" in src
    assert "total_next=int(round(subtotal + gst))" in src


def test_summary_reuses_billing_math_and_never_reprices():
    """billing_math is the single source of truth for price, GST and overage."""
    import backend.routers.payments as m

    src = inspect.getsource(m.billing_summary)
    assert "effective_price(" in src, "base must come from billing_math"
    assert "_gst_on(" in src, "GST must come from billing_math (respects GST_WAIVED)"
    assert "p.overage_per_min" not in src or "plan_def.overage_per_min" in src


def test_summary_is_scoped_to_the_callers_own_org():
    """RULE 1: one clinic's money must never be visible to another."""
    import backend.routers.payments as m

    src = inspect.getsource(m.billing_summary)
    assert "_load_my_org(current_user, db)" in src
    assert "BillingCycle.org_id == org.id" in src


def test_overage_can_never_be_negative():
    import backend.routers.payments as m

    src = inspect.getsource(m.billing_summary)
    assert "over_min = max(0, used_min - included)" in src


def test_autopay_flag_is_reported_not_assumed():
    """Autopay is designed but unbuilt; the page must render the real state."""
    import backend.routers.payments as m

    assert "autopay_enabled" in inspect.getsource(m.BillingSummary)

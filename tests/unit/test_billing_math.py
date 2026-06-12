"""billing_math — the money numbers on the super-admin console must be right.

Pricing is FINAL per CLAUDE.md: solo 1999/100min/Rs3, clinic 7999/2100/Rs3,
multi 16999/4200/Rs2.50. Cost floor Rs1.49/min + Rs1000/DID/month.
"""
from backend.services.billing_math import (
    PLANS,
    call_blocked,
    included_minutes,
    minutes_exhausted,
    month_expense,
    month_revenue,
)


def test_plan_table_matches_claude_md():
    assert PLANS["solo"].base_rupees == 1999
    assert PLANS["solo"].included_minutes == 100
    assert PLANS["clinic"].base_rupees == 7999
    assert PLANS["clinic"].included_minutes == 2100
    assert PLANS["multi"].overage_per_min == 2.5


def test_revenue_active_within_bucket_is_base_only():
    assert month_revenue("clinic", "active", 2000) == 7999


def test_revenue_overage_charged():
    # clinic: 2100 included, 100 over at Rs3
    assert month_revenue("clinic", "active", 2200) == 7999 + 300
    # multi: Rs2.50 overage
    assert month_revenue("multi", "active", 4204) == 16999 + 10.0


def test_trial_paused_cancelled_pay_nothing():
    for status in ("trial", "paused", "cancelled"):
        assert month_revenue("clinic", status, 5000) == 0.0


def test_unknown_plan_zero_revenue():
    assert month_revenue("enterprise", "active", 100) == 0.0


def test_expense_minutes_plus_dids():
    assert month_expense(1000, 2) == round(1000 * 1.49 + 2000, 2)
    assert month_expense(0, 1) == 1000  # DID rent even with zero usage


def test_minutes_exhausted_boundary():
    assert minutes_exhausted("solo", 99.9) is False
    assert minutes_exhausted("solo", 100) is True
    assert minutes_exhausted("unknown", 99999) is False  # no bucket, never blocks


def test_call_blocked_matrix():
    assert call_blocked("paused", "clinic", False, 0) == "paused"
    assert call_blocked("cancelled", "clinic", False, 0) == "cancelled"
    # hard block off -> overage allowed, never blocked
    assert call_blocked("active", "clinic", False, 99999) is None
    # hard block on but bucket not exhausted
    assert call_blocked("active", "clinic", True, 2099) is None
    # hard block on + exhausted
    assert call_blocked("active", "clinic", True, 2100) == "minutes_exhausted"
    # hard block applies to trial orgs too once their bucket is gone
    assert call_blocked("trial", "clinic", True, 5000) == "minutes_exhausted"

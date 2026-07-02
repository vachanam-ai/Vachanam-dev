"""billing_math — the money numbers on the super-admin console must be right.

Pricing per CLAUDE.md (repriced 2026-06-16): solo 1999/100min/Rs5, clinic
9999/1800/Rs5, multi 15999/3600/Rs5. Variable cost Rs2.0/min + Rs1000/DID/month.
"""
from backend.services.billing_math import (
    PLANS,
    TRIAL_MINUTES,
    call_blocked,
    included_minutes,
    included_minutes_for,
    minutes_exhausted,
    month_expense,
    month_revenue,
    overage_breakdown,
)


def test_overage_breakdown_solo_1000_minutes():
    # The #6 scenario: solo plan (100 included), 1000 minutes used.
    bd = overage_breakdown("solo", 1000)
    assert bd["included_minutes"] == 100
    assert bd["overage_minutes"] == 900
    assert bd["overage_rate"] == 5.0
    assert bd["overage_amount"] == 4500.0       # 900 × ₹5
    assert bd["gst"] == 810.0                    # 18% of 4500
    assert bd["total_with_gst"] == 5310.0
    assert bd["amount_paise"] == 531000          # exact paise sent to Razorpay


def test_overage_breakdown_no_overage_within_bucket():
    bd = overage_breakdown("clinic", 1200)       # under the 1800 bucket
    assert bd["overage_minutes"] == 0
    assert bd["overage_amount"] == 0.0
    assert bd["amount_paise"] == 0


def test_overage_breakdown_respects_minute_adjustment():
    # +500 goodwill minutes on solo → bucket 600, so 1000 used = 400 overage.
    bd = overage_breakdown("solo", 1000, "active", 500)
    assert bd["included_minutes"] == 600
    assert bd["overage_minutes"] == 400
    assert bd["amount_paise"] == int(round(400 * 5 * 1.18 * 100))


def test_trial_org_gets_flat_500_minutes_regardless_of_plan():
    # Bug (2026-06-23): trial clinics showed the plan's bucket (solo=100) instead
    # of the 500-min trial grant. The trial allowance is flat across all plans.
    assert TRIAL_MINUTES == 500
    assert included_minutes_for("solo", "trial") == 500
    assert included_minutes_for("clinic", "trial") == 500
    assert included_minutes_for("multi", "trial") == 500


def test_non_trial_org_gets_plan_bucket():
    assert included_minutes_for("solo", "active") == 100
    assert included_minutes_for("clinic", "active") == 1800
    assert included_minutes_for("multi", "paused") == 3600


def test_minutes_adjustment_applies_and_floors_at_zero():
    # Super-admin per-clinic override: signed delta on top of the bucket.
    assert included_minutes_for("solo", "active", 50) == 150
    assert included_minutes_for("clinic", "active", -300) == 1500
    assert included_minutes_for("solo", "trial", 100) == 600
    # Never goes negative.
    assert included_minutes_for("solo", "active", -9999) == 0


def test_plan_table_matches_claude_md():
    assert PLANS["solo"].base_rupees == 1999
    assert PLANS["solo"].included_minutes == 100
    assert PLANS["solo"].overage_per_min == 5.0
    assert PLANS["clinic"].base_rupees == 9999
    assert PLANS["clinic"].included_minutes == 1800
    assert PLANS["multi"].base_rupees == 15999
    assert PLANS["multi"].included_minutes == 3600
    assert PLANS["multi"].overage_per_min == 5.0


def test_revenue_active_within_bucket_is_base_only():
    assert month_revenue("clinic", "active", 1500) == 9999  # under the 1,800 bucket


def test_revenue_overage_charged():
    # clinic: 1,800 included, 200 over at Rs5
    assert month_revenue("clinic", "active", 2000) == 9999 + 1000
    # multi: 3,600 included, 100 over at Rs5
    assert month_revenue("multi", "active", 3700) == 15999 + 500


def test_trial_paused_cancelled_pay_nothing():
    for status in ("trial", "paused", "cancelled"):
        assert month_revenue("clinic", status, 5000) == 0.0


def test_unknown_plan_zero_revenue():
    assert month_revenue("enterprise", "active", 100) == 0.0


def test_expense_minutes_plus_dids():
    assert month_expense(1000, 2) == round(1000 * 2.0 + 2000, 2)
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
    assert call_blocked("active", "clinic", True, 1799) is None
    # hard block on + exhausted
    assert call_blocked("active", "clinic", True, 1800) == "minutes_exhausted"
    # hard block applies to trial orgs too once their bucket is gone
    assert call_blocked("trial", "clinic", True, 5000) == "minutes_exhausted"


def test_b3_hard_block_honors_trial_grant_and_adjustment():
    # B3: a solo-plan TRIAL org has a 500-min grant, not the 100-min plan
    # bucket. The old gate blocked at 100 while the dashboard showed 400 left.
    assert minutes_exhausted("solo", 100, status="trial") is False
    assert minutes_exhausted("solo", 499, status="trial") is False
    assert minutes_exhausted("solo", 500, status="trial") is True
    assert call_blocked("trial", "solo", True, 100) is None
    assert call_blocked("trial", "solo", True, 500) == "minutes_exhausted"

    # A positive super-admin adjustment extends the active bucket; a negative
    # one shrinks it — the gate must track both, exactly like the donut.
    assert minutes_exhausted("solo", 100, status="active") is True
    assert minutes_exhausted("solo", 100, status="active", adjustment=50) is False
    assert minutes_exhausted("solo", 150, status="active", adjustment=50) is True
    assert call_blocked("active", "solo", True, 120, adjustment=50) is None
    assert call_blocked("active", "solo", True, 150, adjustment=50) == "minutes_exhausted"
    assert call_blocked("active", "clinic", True, 1700, adjustment=-200) == "minutes_exhausted"

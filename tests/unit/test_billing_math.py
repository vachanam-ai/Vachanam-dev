"""billing_math — the money numbers on the super-admin console must be right.

Pricing per CLAUDE.md (repriced 2026-07-11): solo/Starter 5999/700min/Rs5,
clinic 9999/1500/Rs5, multi 17999/3000/Rs5. Trial = 300 min, HARD-blocked on
exhaust. Every plan holds >=40% margin at worst case (Rs3/min + Rs1,500 infra).
"""
from backend.services.billing_math import (
    PLAN_LANGUAGES,
    PLANS,
    PREMIUM_VOICE_PLANS,
    TRIAL_MINUTES,
    call_blocked,
    included_minutes_for,
    minutes_exhausted,
    month_expense,
    month_revenue,
    overage_breakdown,
    subscription_order_breakdown,
)


def test_subscription_order_first_activation_is_base_plus_gst():
    bd = subscription_order_breakdown("solo")
    assert bd["base"] == 5999
    assert bd["overage_minutes"] == 0
    assert bd["gst"] == round(5999 * 0.18, 2)
    assert bd["amount_paise"] == int(round(5999 * 1.18 * 100))


def test_subscription_order_renewal_adds_overage_then_gst():
    # Vinay's example (2026-07-12): 50 extra minutes → ₹250. Clinic renewal:
    # 9,999 + 250 = 10,249 subtotal → +18% GST = ₹12,093.82.
    bd = subscription_order_breakdown("clinic", cycle_minutes_used=1550)
    assert bd["overage_minutes"] == 50
    assert bd["overage_amount"] == 250.0
    assert bd["gst"] == 1844.82
    assert bd["total"] == 12093.82
    assert bd["amount_paise"] == 1209382


def test_subscription_order_honors_minute_adjustment():
    # +100 goodwill minutes → bucket 1600, so 1550 used = no overage.
    bd = subscription_order_breakdown("clinic", cycle_minutes_used=1550, adjustment=100)
    assert bd["overage_minutes"] == 0
    assert bd["amount_paise"] == int(round(9999 * 1.18 * 100))


def test_overage_breakdown_solo_1000_minutes():
    # solo/Starter plan (700 included), 1000 minutes used.
    bd = overage_breakdown("solo", 1000)
    assert bd["included_minutes"] == 700
    assert bd["overage_minutes"] == 300
    assert bd["overage_rate"] == 5.0
    assert bd["overage_amount"] == 1500.0       # 300 × ₹5
    assert bd["gst"] == 270.0                    # 18% of 1500
    assert bd["total_with_gst"] == 1770.0
    assert bd["amount_paise"] == 177000          # exact paise sent to Razorpay


def test_overage_breakdown_no_overage_within_bucket():
    bd = overage_breakdown("clinic", 1200)       # under the 1,500 bucket
    assert bd["overage_minutes"] == 0
    assert bd["overage_amount"] == 0.0
    assert bd["amount_paise"] == 0


def test_overage_breakdown_respects_minute_adjustment():
    # +500 goodwill minutes on solo → bucket 1200, so 1500 used = 300 overage.
    bd = overage_breakdown("solo", 1500, "active", 500)
    assert bd["included_minutes"] == 1200
    assert bd["overage_minutes"] == 300
    assert bd["amount_paise"] == int(round(300 * 5 * 1.18 * 100))


def test_trial_org_gets_flat_300_minutes_regardless_of_plan():
    # The trial allowance is flat across all plans (300 since 2026-07-11).
    assert TRIAL_MINUTES == 300
    assert included_minutes_for("solo", "trial") == 300
    assert included_minutes_for("clinic", "trial") == 300
    assert included_minutes_for("multi", "trial") == 300


def test_non_trial_org_gets_plan_bucket():
    assert included_minutes_for("solo", "active") == 700
    assert included_minutes_for("clinic", "active") == 1500
    assert included_minutes_for("multi", "paused") == 3000


def test_minutes_adjustment_applies_and_floors_at_zero():
    # Super-admin per-clinic override: signed delta on top of the bucket.
    assert included_minutes_for("solo", "active", 50) == 750
    assert included_minutes_for("clinic", "active", -300) == 1200
    assert included_minutes_for("solo", "trial", 100) == 400
    # Never goes negative.
    assert included_minutes_for("solo", "active", -9999) == 0


def test_plan_table_matches_claude_md():
    assert PLANS["solo"].base_rupees == 5999
    assert PLANS["solo"].included_minutes == 700
    assert PLANS["solo"].overage_per_min == 5.0
    assert PLANS["solo"].max_doctors == 1
    assert PLANS["solo"].display_name == "Starter"
    assert PLANS["clinic"].base_rupees == 9999
    assert PLANS["clinic"].included_minutes == 1500
    assert PLANS["clinic"].max_doctors == 5
    assert PLANS["multi"].base_rupees == 17999
    assert PLANS["multi"].included_minutes == 3000
    assert PLANS["multi"].overage_per_min == 5.0
    assert PLANS["multi"].max_doctors is None  # unlimited


def test_every_plan_holds_40pct_margin_at_worst_case():
    """The Vinay invariant (2026-07-11): full use of the included bucket at
    Rs3/min + Rs1,500 infra (1 DID) must leave >=40% gross margin. This test
    is the guard that stops a future 'more generous minutes' edit from
    silently breaking the economics."""
    WORST_COST_PER_MIN, INFRA = 3.0, 1500.0
    for key, p in PLANS.items():
        cost = p.included_minutes * WORST_COST_PER_MIN + INFRA
        margin = (p.base_rupees - cost) / p.base_rupees
        assert margin >= 0.399, f"{key}: worst-case margin {margin:.1%} < 40%"
    # Overage must hold the same bar.
    for p in PLANS.values():
        assert (p.overage_per_min - WORST_COST_PER_MIN) / p.overage_per_min >= 0.399


def test_plan_feature_gates_shape():
    assert PLAN_LANGUAGES["solo"] == ["te"]
    assert PLAN_LANGUAGES["clinic"] == ["te", "hi", "en"]
    assert PLAN_LANGUAGES["multi"] is None      # all languages
    assert PREMIUM_VOICE_PLANS == ("clinic", "multi")


def test_revenue_active_within_bucket_is_base_only():
    assert month_revenue("clinic", "active", 1400) == 9999  # under the 1,500 bucket


def test_revenue_overage_charged():
    # clinic: 1,500 included, 200 over at Rs5
    assert month_revenue("clinic", "active", 1700) == 9999 + 1000
    # multi: 3,000 included, 100 over at Rs5
    assert month_revenue("multi", "active", 3100) == 17999 + 500


def test_trial_paused_cancelled_pay_nothing():
    for status in ("trial", "paused", "cancelled"):
        assert month_revenue("clinic", status, 5000) == 0.0


def test_unknown_plan_zero_revenue():
    assert month_revenue("enterprise", "active", 100) == 0.0


def test_expense_minutes_plus_dids():
    assert month_expense(1000, 2) == round(1000 * 2.0 + 2000, 2)
    assert month_expense(0, 1) == 1000  # DID rent even with zero usage


def test_minutes_exhausted_boundary():
    assert minutes_exhausted("solo", 699.9) is False
    assert minutes_exhausted("solo", 700) is True
    assert minutes_exhausted("unknown", 99999) is False  # no bucket, never blocks


def test_call_blocked_matrix():
    assert call_blocked("paused", "clinic", False, 0) == "paused"
    assert call_blocked("cancelled", "clinic", False, 0) == "cancelled"
    # hard block off -> overage allowed, never blocked (paying orgs)
    assert call_blocked("active", "clinic", False, 99999) is None
    # hard block on but bucket not exhausted
    assert call_blocked("active", "clinic", True, 1499) is None
    # hard block on + exhausted
    assert call_blocked("active", "clinic", True, 1500) == "minutes_exhausted"


def test_trial_always_hard_blocks_on_exhaust():
    """2026-07-11: trial minutes are Vachanam's own cash — the 300-min bucket
    is enforced even when the super-admin hard_block flag is OFF (the flag
    governs PAYING orgs' overage behavior, not free trials)."""
    assert call_blocked("trial", "clinic", False, 299) is None
    assert call_blocked("trial", "clinic", False, 300) == "minutes_exhausted"
    assert call_blocked("trial", "solo", False, 300) == "minutes_exhausted"
    # goodwill adjustment still extends the trial bucket
    assert call_blocked("trial", "solo", False, 300, adjustment=100) is None


def test_b3_hard_block_honors_trial_grant_and_adjustment():
    # B3: a solo-plan TRIAL org has the flat trial grant, not the plan bucket.
    assert minutes_exhausted("solo", 100, status="trial") is False
    assert minutes_exhausted("solo", 299, status="trial") is False
    assert minutes_exhausted("solo", 300, status="trial") is True
    assert call_blocked("trial", "solo", True, 100) is None
    assert call_blocked("trial", "solo", True, 300) == "minutes_exhausted"

    # A positive super-admin adjustment extends the active bucket; a negative
    # one shrinks it — the gate must track both, exactly like the donut.
    assert minutes_exhausted("solo", 700, status="active") is True
    assert minutes_exhausted("solo", 700, status="active", adjustment=50) is False
    assert minutes_exhausted("solo", 750, status="active", adjustment=50) is True
    assert call_blocked("active", "solo", True, 720, adjustment=50) is None
    assert call_blocked("active", "solo", True, 750, adjustment=50) == "minutes_exhausted"
    assert call_blocked("active", "clinic", True, 1400, adjustment=-200) == "minutes_exhausted"

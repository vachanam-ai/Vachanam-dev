"""billing_math — the money numbers on the super-admin console must be right.

Public pricing: Voice Rs1,999 + Rs6/min; WhatsApp-only Rs1,999; WhatsApp
add-on Rs1,499. Founding trial = unlimited for 14 days with a hard expiry.
"""
from backend.services.billing_math import (
    PLAN_LANGUAGES,
    PLANS,
    TRIAL_MINUTES,
    call_blocked,
    included_minutes_for,
    minutes_exhausted,
    month_expense,
    month_revenue,
    overage_breakdown,
    subscription_order_breakdown,
)


def test_subscription_order_first_activation_is_list_price():
    # 2026-08-04: discounts removed — first activation bills the list price.
    bd = subscription_order_breakdown("solo")
    assert bd["base"] == 1999 and bd["is_offer"] is False
    assert bd["overage_minutes"] == 0
    assert bd["gst"] == 0.0  # GST_WAIVED still True — a separate lever
    assert bd["amount_paise"] == 199900


def test_subscription_order_after_offer_window_standard_base(monkeypatch):
    # 4th month on: standard price. GST math itself preserved for when Vinay
    # restores it (GST_WAIVED=False) — old #341 contract still holds then.
    from datetime import datetime, timedelta, timezone

    from backend.services import billing_math as bm

    old_start = datetime.now(timezone.utc) - timedelta(days=200)
    bd = subscription_order_breakdown("clinic", cycle_minutes_used=50,
                                      subscription_started_at=old_start)
    assert bd["base"] == 4999 and bd["is_offer"] is False
    assert bd["overage_minutes"] == 50 and bd["overage_amount"] == 300.0
    assert bd["gst"] == 0.0  # still waived globally for now
    monkeypatch.setattr(bm, "GST_WAIVED", False)
    bd2 = subscription_order_breakdown("clinic", cycle_minutes_used=50,
                                       subscription_started_at=old_start)
    assert bd2["gst"] == 953.82 and bd2["total"] == 6252.82
    assert bd2["amount_paise"] == 625282


def test_subscription_order_honors_minute_adjustment():
    # +100 goodwill minutes → bucket 1600, so 1550 used = no overage.
    bd = subscription_order_breakdown("clinic", cycle_minutes_used=50, adjustment=100)
    assert bd["overage_minutes"] == 0
    assert bd["amount_paise"] == 499900  # list base, no GST


def test_overage_breakdown_solo_1000_minutes():
    # Basic plan (400 included), 1000 minutes used.
    bd = overage_breakdown("solo", 1000)
    assert bd["included_minutes"] == 0
    assert bd["overage_minutes"] == 1000
    assert bd["overage_rate"] == 6.0
    assert bd["overage_amount"] == 6000.0
    assert bd["gst"] == 0.0                      # GST waived (#391)
    assert bd["total_with_gst"] == 6000.0
    assert bd["amount_paise"] == 600000


def test_overage_breakdown_zero_usage_is_zero():
    bd = overage_breakdown("clinic", 0)
    assert bd["overage_minutes"] == 0
    assert bd["overage_amount"] == 0.0
    assert bd["amount_paise"] == 0


def test_overage_breakdown_respects_minute_adjustment():
    # +500 goodwill minutes on Basic → bucket 900, so 1500 used = 600 overage.
    bd = overage_breakdown("solo", 1500, "active", 500)
    assert bd["included_minutes"] == 500
    assert bd["overage_minutes"] == 1000
    assert bd["amount_paise"] == 1000 * 6 * 100  # GST waived


def test_trial_org_is_unmetered_regardless_of_plan():
    from backend.services.billing_math import TRIAL_UNLIMITED

    assert TRIAL_MINUTES == 0 and TRIAL_UNLIMITED is True
    assert included_minutes_for("solo", "trial") == 0
    assert included_minutes_for("clinic", "trial") == 0
    assert included_minutes_for("multi", "trial") == 0
    assert overage_breakdown("solo", 100_000, "trial")["amount_paise"] == 0


def test_non_trial_org_has_no_bundled_bucket():
    assert included_minutes_for("solo", "active") == 0
    assert included_minutes_for("clinic", "active") == 0
    assert included_minutes_for("multi", "paused") == 0


def test_minutes_adjustment_applies_and_floors_at_zero():
    # Super-admin per-clinic override: signed delta on top of the bucket.
    assert included_minutes_for("solo", "active", 50) == 50
    assert included_minutes_for("clinic", "active", -300) == 0
    assert included_minutes_for("solo", "trial", 100) == 0
    # Never goes negative.
    assert included_minutes_for("solo", "active", -9999) == 0


def test_plan_table_matches_claude_md():
    assert PLANS["solo"].base_rupees == 1999
    assert PLANS["solo"].included_minutes == 0
    assert PLANS["solo"].overage_per_min == 6.0
    assert PLANS["solo"].max_doctors is None
    assert PLANS["solo"].display_name == "Vachanam Voice"
    assert PLANS["clinic"].base_rupees == 4999
    assert PLANS["clinic"].included_minutes == 0
    assert PLANS["clinic"].max_doctors == 10
    assert PLANS["clinic"].display_name == "Growth (legacy)"
    assert PLANS["multi"].base_rupees == 6999
    assert PLANS["multi"].included_minutes == 0
    assert PLANS["multi"].overage_per_min == 6.0
    assert PLANS["multi"].max_doctors is None  # unlimited


def test_public_hybrid_plan_covers_fixed_cost_and_doubles_variable_cost():
    """Platform fee recovers fixed costs; metered voice carries 100% markup."""
    from backend.services.billing_math import (
        SELLABLE_PLANS, VARIABLE_COST_PER_MIN, fixed_cost_for,
    )

    assert SELLABLE_PLANS == frozenset({"solo", "wa"})
    for key in SELLABLE_PLANS:
        assert PLANS[key].base_rupees >= fixed_cost_for(key)
        if PLANS[key].has_voice:
            assert PLANS[key].overage_per_min >= VARIABLE_COST_PER_MIN * 2


def test_wa_plan_is_1999_with_no_voice():
    """WhatsApp-only plan (Vinay 2026-08-02, spec 2026-08-02-whatsapp-pricing).
    Zero minutes and zero overage are deliberate: it buys no voice at all, so
    a call is a configuration error rather than an overage."""
    wa = PLANS["wa"]
    assert wa.base_rupees == 1999
    assert wa.included_minutes == 0
    assert wa.overage_per_min == 0.0
    assert wa.max_doctors == 3
    assert wa.display_name == "WhatsApp"


def test_whatsapp_enabled_gate():
    """Single gate for every WhatsApp capability check: included in the plan,
    or bought as an add-on by legacy Lite/Basic."""
    from backend.services.billing_math import whatsapp_enabled

    assert whatsapp_enabled("wa", False) is True
    assert whatsapp_enabled("clinic", False) is False
    assert whatsapp_enabled("multi", False) is False
    assert whatsapp_enabled("lite", False) is False
    assert whatsapp_enabled("solo", False) is False
    assert whatsapp_enabled("lite", True) is True
    assert whatsapp_enabled("solo", True) is True
    assert whatsapp_enabled("clinic", True) is True
    assert whatsapp_enabled("multi", True) is True
    # An add-on flag must never conjure WhatsApp onto a plan that cannot buy it.
    assert whatsapp_enabled("", True) is False


def test_margin_invariant_costs_a_did_only_to_voice_plans():
    """The old flat INFRA=1500 folded in a DID that every plan was assumed to
    buy. Applied to a WhatsApp-only plan that yields 0*3 + 1500 = 1500 against
    a 1499 price — a NEGATIVE margin for what is in fact our best plan."""
    from backend.services.billing_math import BASE_INFRA, DID_RUPEES, fixed_cost_for

    assert DID_RUPEES + BASE_INFRA == 1499.0
    for voice_plan in ("lite", "solo", "clinic"):
        assert fixed_cost_for(voice_plan) == 1499.0
    assert fixed_cost_for("multi") == 2998.0
    assert fixed_cost_for("wa") == BASE_INFRA

    wa = PLANS["wa"]
    margin = (wa.base_rupees - fixed_cost_for("wa")) / wa.base_rupees
    assert margin >= 0.75, f"wa margin {margin:.1%} — should be our best plan"


def test_whatsapp_prices_are_explicit():
    """Standalone and Voice add-on prices are intentional public products."""
    from backend.services.billing_math import (
        PLANS,
        WHATSAPP_ADDON_PLANS,
        WHATSAPP_ADDON_RUPEES,
    )

    assert WHATSAPP_ADDON_RUPEES == 1499
    assert PLANS["wa"].base_rupees == 1999
    assert WHATSAPP_ADDON_PLANS == frozenset({"lite", "solo", "clinic", "multi"})


def test_lite_plan_economics():
    """Lite (Vinay 2026-07-15): ₹1,999, 150 min, 1 DID, 1 doctor, all
    languages, follow-up INCLUDED. Deliberately NOT 40%-worst (per-clinic
    fixed cost too large under ₹2k); holds ~35% at TYPICAL cost, and overage
    protects the downside."""
    from backend.services.billing_math import FOLLOWUP_PLANS

    lite = PLANS["lite"]
    assert lite.base_rupees == 1999
    assert lite.included_minutes == 150
    assert lite.overage_per_min == 6.0
    assert lite.max_doctors == 3  # 2026-07-17 (Vinay): 1 -> 3, zero-variable-cost
    assert lite.display_name == "Lite (legacy)"
    assert PLAN_LANGUAGES["lite"] is None  # all languages

    # Typical cost (Rs2/min + Rs1,000 DID) at full bucket >= 30% margin.
    typical_cost = lite.included_minutes * 2.0 + 1000.0
    typical_margin = (lite.base_rupees - typical_cost) / lite.base_rupees
    assert typical_margin >= 0.30, f"lite typical margin {typical_margin:.1%}"

    # Follow-up loop included (cloning removed platform-wide 2026-07-24).
    assert "lite" in FOLLOWUP_PLANS


def test_plan_feature_gates_shape():
    # 2026-07-12 (Vinay): ALL plans carry all languages (zero variable cost);
    # differentiation is minutes/doctors/premium voice.
    assert PLAN_LANGUAGES["lite"] is None
    assert PLAN_LANGUAGES["solo"] is None
    assert PLAN_LANGUAGES["clinic"] is None
    assert PLAN_LANGUAGES["multi"] is None
    # Follow-up on every plan; voice cloning REMOVED platform-wide 2026-07-24
    # (the old CLONING_PLANS / PREMIUM_VOICE_PLANS gates are gone).
    import backend.services.billing_math as bm
    from backend.services.billing_math import FOLLOWUP_PLANS

    assert set(FOLLOWUP_PLANS) == {"lite", "solo", "clinic", "multi", "wa"}
    assert not hasattr(bm, "CLONING_PLANS") and not hasattr(bm, "cloning_allowed")


def test_revenue_active_zero_usage_is_base_only():
    assert month_revenue("clinic", "active", 0) == 4999


def test_revenue_overage_charged():
    assert month_revenue("clinic", "active", 1700) == 4999 + 1700 * 6
    assert month_revenue("multi", "active", 3100) == 6999 + 3100 * 6


def test_trial_paused_cancelled_pay_nothing():
    for status in ("trial", "paused", "cancelled"):
        assert month_revenue("clinic", status, 5000) == 0.0


def test_unknown_plan_zero_revenue():
    assert month_revenue("enterprise", "active", 100) == 0.0


def test_expense_minutes_plus_dids():
    assert month_expense(1000, 2) == round(1000 * 2.9 + 2400, 2)
    assert month_expense(0, 1) == 1200  # DID rent even with zero usage


def test_minutes_exhausted_boundary():
    assert minutes_exhausted("solo", 399.9) is False
    assert minutes_exhausted("solo", 400) is False
    assert minutes_exhausted("unknown", 99999) is False  # no bucket, never blocks


def test_call_blocked_matrix():
    assert call_blocked("paused", "clinic", False, 0) == "paused"
    assert call_blocked("cancelled", "clinic", False, 0) == "cancelled"
    # hard block off -> overage allowed, never blocked (paying orgs)
    assert call_blocked("active", "clinic", False, 99999) is None
    # hard block on but bucket not exhausted
    assert call_blocked("active", "clinic", True, 1499) is None
    # Usage-only paying plans never hard-block on minutes.
    assert call_blocked("active", "clinic", True, 1500) is None


def test_trial_never_blocks_on_minutes_before_expiry():
    for used in (0, 30, 500, 100_000):
        assert call_blocked("trial", "clinic", False, used) is None
        assert call_blocked("trial", "solo", True, used) is None


def test_trial_expiry_hard_stops_even_before_pause_job():
    """Vinay 2026-07-17 ("hard stop after free trial limit ended"): an expired
    trial blocks IMMEDIATELY via call_blocked — no free service in the window
    before the daily trial_pause job flips status to paused. Usage remains
    unlimited until this exact time boundary."""
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    assert call_blocked("trial", "clinic", False, 0,
                        trial_ends_at=now + timedelta(hours=1)) is None
    assert call_blocked("trial", "clinic", False, 0,
                        trial_ends_at=now - timedelta(minutes=1)) == "trial_expired"
    # naive datetime from the DB is treated as UTC, still blocks
    assert call_blocked("trial", "clinic", False, 0,
                        trial_ends_at=(now - timedelta(days=2)).replace(tzinfo=None)) == "trial_expired"


def test_blocked_call_speaks_emergency_number_source_guard():
    """The blocked-call path must offer the clinic's escalation number — a
    patient must never get a dead end (RULE 8)."""
    from pathlib import Path

    src = Path("agent/livekit_minimal/agent.py").read_text(encoding="utf-8")
    assert "emergency_contact" in src.split("_blocked_text = lines.service_blocked")[1][:1200]


def test_b3_hard_block_honors_unlimited_trial_and_paid_adjustment():
    assert minutes_exhausted("solo", 100_000, status="trial") is False
    assert call_blocked("trial", "solo", True, 100_000) is None

    # A positive super-admin adjustment extends the active bucket; a negative
    # one shrinks it — the gate must track both, exactly like the donut.
    assert minutes_exhausted("solo", 400, status="active") is False
    assert minutes_exhausted("solo", 49, status="active", adjustment=50) is False
    assert minutes_exhausted("solo", 50, status="active", adjustment=50) is True
    assert call_blocked("active", "solo", True, 49, adjustment=50) is None
    assert call_blocked("active", "solo", True, 50, adjustment=50) == "minutes_exhausted"
    assert call_blocked("active", "clinic", True, 1400, adjustment=-200) is None


def test_whatsapp_plans_gate():
    """Only the legacy WA plan bundles WhatsApp; current plans use add-ons."""
    from backend.services.billing_math import WHATSAPP_PLANS, whatsapp_enabled

    assert WHATSAPP_PLANS == {"wa"}
    for key in ("lite", "solo", "clinic", "multi"):
        assert key not in WHATSAPP_PLANS
        assert whatsapp_enabled(key) is False


# ── autopay mandate ceiling (Vinay 2026-08-07) ───────────────────────────────

def test_mandate_ceiling_covers_a_heavy_but_plausible_month():
    """The ceiling must survive the worst month it claims to cover: base +
    add-on + the modelled overage, WITH GST switched back on."""
    from backend.services import billing_math as bm

    for plan, p in bm.PLANS.items():
        if not p.has_voice:
            continue
        for addon in (False, True):
            ceiling = bm.mandate_max_amount(plan, addon)
            worst = (
                p.base_rupees
                + (bm.WHATSAPP_ADDON_RUPEES
                   if addon and plan in bm.WHATSAPP_ADDON_PLANS else 0)
                + bm.mandate_worst_overage_minutes(plan) * p.overage_per_min
            ) * 1.18  # GST back on — the mandate must not need re-signing
            assert ceiling >= worst, (
                f"{plan} ceiling {ceiling} cannot cover its own worst case {worst:.0f}"
            )


def test_mandate_ceiling_stays_low_enough_to_sign():
    """Vinay: "keep it as low as possible". A ceiling many multiples of the
    monthly price is what makes a clinic refuse to authorise the mandate."""
    from backend.services import billing_math as bm

    # The low platform fee makes a ratio misleading: the mandate must also
    # cover 500 billable minutes. Keep the visible absolute ceiling bounded.
    assert bm.mandate_max_amount("solo", False) == 6_000


def test_founding_offer_is_one_hundred_clinics_and_no_paid_cycle_credit():
    from backend.services.billing_math import (
        FOUNDING_CLINIC_SLOTS, FOUNDING_CREDIT_MINUTES,
    )

    assert FOUNDING_CLINIC_SLOTS == 100
    assert FOUNDING_CREDIT_MINUTES == 0


def test_founding_credit_is_consumed_before_six_rupee_usage_billing():
    from backend.services.billing_math import overage_breakdown

    at_credit = overage_breakdown("solo", 500, adjustment=500)
    first_billable_minute = overage_breakdown("solo", 501, adjustment=500)
    next_cycle = overage_breakdown("solo", 1, adjustment=0)

    assert at_credit["overage_minutes"] == 0
    assert at_credit["overage_amount"] == 0
    assert first_billable_minute["overage_minutes"] == 1
    assert first_billable_minute["overage_amount"] == 6
    assert next_cycle["overage_amount"] == 6


def test_paid_cycle_allowance_outlives_the_staging_credit_field():
    from backend.services.billing_math import allowance_adjustment

    assert allowance_adjustment(
        "solo", cycle_included=500, founding_credit=0
    ) == 500
    assert allowance_adjustment(
        "solo", cycle_included=None, founding_credit=500
    ) == 500


def test_mandate_ceiling_is_a_round_number():
    from backend.services import billing_math as bm

    for plan in bm.PLANS:
        assert bm.mandate_max_amount(plan) % 500 == 0


def test_whatsapp_only_plan_has_no_overage_headroom():
    """`wa` buys no telephony, so there is no overage to leave room for."""
    from backend.services import billing_math as bm

    assert bm.mandate_worst_overage_minutes("wa") == 0
    assert bm.mandate_max_amount("wa") >= bm.PLANS["wa"].base_rupees


def test_addon_only_widens_the_ceiling_for_plans_that_can_buy_it():
    from backend.services import billing_math as bm

    for plan in ("lite", "solo", "clinic", "multi"):
        assert bm.mandate_max_amount(plan, True) > bm.mandate_max_amount(plan, False)


def test_unknown_plan_authorises_nothing():
    from backend.services import billing_math as bm

    assert bm.mandate_max_amount("nonexistent") == 0

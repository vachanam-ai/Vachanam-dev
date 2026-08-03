"""Buying WhatsApp is one charge now, then one invoice forever after.

Vinay 2026-08-03: "implement a button to add on whatsapp. which should prompt
for payment of 1499. and from next month on entire billing should come together
(number+whatsapp)." First month full price, not pro-rated (his call).

The invariants that matter on a money path:
  * the add-on is charged ONCE mid-cycle, then folded into the plan invoice —
    never both, never neither;
  * a plan that already bundles WhatsApp is never charged for it again;
  * GST is computed on the whole subtotal, not per line.
"""
import pytest

from backend.services.billing_math import (
    GST_WAIVED,
    PLANS,
    WHATSAPP_ADDON_PLANS,
    WHATSAPP_ADDON_RUPEES,
    WHATSAPP_PLANS,
    subscription_order_breakdown,
    whatsapp_addon_order_breakdown,
)


def test_the_one_off_charge_is_exactly_the_advertised_price():
    bd = whatsapp_addon_order_breakdown()
    assert bd["base"] == WHATSAPP_ADDON_RUPEES == 1_499
    expected = 1_499 if GST_WAIVED else round(1_499 * 1.18, 2)
    assert bd["total"] == expected
    assert bd["amount_paise"] == int(round(expected * 100))


@pytest.mark.parametrize("plan", sorted(WHATSAPP_ADDON_PLANS))
def test_the_renewal_carries_the_addon_for_addon_plans(plan):
    """"from next month on entire billing should come together" — one invoice."""
    without = subscription_order_breakdown(plan, whatsapp_addon=False)
    with_wa = subscription_order_breakdown(plan, whatsapp_addon=True)
    assert without["whatsapp_addon"] == 0.0
    assert with_wa["whatsapp_addon"] == float(WHATSAPP_ADDON_RUPEES)
    assert with_wa["total"] > without["total"]
    # ONE line on ONE invoice, not a second subscription.
    assert with_wa["base"] == without["base"]


@pytest.mark.parametrize("plan", sorted(WHATSAPP_PLANS & set(PLANS)))
def test_a_plan_that_bundles_whatsapp_is_never_charged_twice(plan):
    """clinic/multi/wa already price WhatsApp in. Billing the add-on on top
    would silently overcharge every one of them."""
    with_wa = subscription_order_breakdown(plan, whatsapp_addon=True)
    assert with_wa["whatsapp_addon"] == 0.0
    assert with_wa["total"] == subscription_order_breakdown(plan)["total"]


def test_gst_is_charged_on_the_whole_subtotal_not_per_line():
    bd = subscription_order_breakdown("solo", cycle_minutes_used=0, whatsapp_addon=True)
    subtotal = bd["base"] + bd["overage_amount"] + bd["whatsapp_addon"]
    expected_gst = 0.0 if GST_WAIVED else round(subtotal * 0.18, 2)
    assert bd["gst"] == expected_gst
    assert bd["total"] == round(subtotal + bd["gst"], 2)


def test_overage_and_the_addon_ride_the_same_invoice():
    """A clinic over its minutes AND on WhatsApp gets one bill with both."""
    bd = subscription_order_breakdown(
        "solo", cycle_minutes_used=PLANS["solo"].included_minutes + 100,
        whatsapp_addon=True,
    )
    assert bd["overage_minutes"] == 100
    assert bd["overage_amount"] == 100 * PLANS["solo"].overage_per_min
    assert bd["whatsapp_addon"] == float(WHATSAPP_ADDON_RUPEES)
    assert bd["total"] == round(
        bd["base"] + bd["overage_amount"] + bd["whatsapp_addon"] + bd["gst"], 2
    )


def test_the_addon_never_changes_the_plan_price_itself():
    """Guards against the add-on being smuggled into `base`, which would break
    the offer-price display and every plan-comparison screen."""
    for plan in sorted(WHATSAPP_ADDON_PLANS):
        assert (
            subscription_order_breakdown(plan, whatsapp_addon=True)["base"]
            == subscription_order_breakdown(plan, whatsapp_addon=False)["base"]
        )

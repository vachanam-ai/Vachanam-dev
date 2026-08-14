"""Create a Razorpay order for a clinic's voice-minute overage.

Razorpay charges a rupee total, not minutes — the per-minute billing is our own
math (`billing_math.overage_breakdown`). This wraps order.create with the
overage amount (in paise) and server-set notes so the order is attributable and
visible in the Razorpay dashboard. Used by the monthly billing path and by
`scripts/generate_fake_bill.py` to demonstrate per-minute overage charging.
"""
from __future__ import annotations

import structlog

from backend.config import settings
from backend.services.billing_math import overage_breakdown

logger = structlog.get_logger()


def get_razorpay_client():
    """Build a Razorpay client from configured keys, or raise if unset."""
    import razorpay

    if not settings.razorpay_key_id or not settings.razorpay_key_secret:
        raise RuntimeError("Razorpay keys not configured")
    return razorpay.Client(auth=(settings.razorpay_key_id, settings.razorpay_key_secret))


def create_overage_order(
    org_id: str,
    plan: str,
    minutes_used: float,
    *,
    status: str = "active",
    adjustment: int = 0,
    client=None,
    cycle_label: str | None = None,
) -> tuple[dict, dict | None]:
    """Compute the overage bill and create a Razorpay order for it.

    Returns (breakdown, order). When there is no overage (amount_paise == 0) the
    order is None — Razorpay rejects zero-amount orders, and there is nothing to
    charge. Notes are set server-side so the webhook/dashboard can trust them.
    """
    bd = overage_breakdown(plan, minutes_used, status, adjustment)
    if bd["amount_paise"] <= 0:
        return bd, None

    client = client or get_razorpay_client()
    payload = {
        "amount": bd["amount_paise"],
        "currency": "INR",
        "receipt": f"overage_{org_id[:8]}_{cycle_label or 'cycle'}",
        "notes": {
            "org_id": org_id,
            "type": "overage",
            "plan": plan,
            "overage_minutes": str(bd["overage_minutes"]),
            "overage_rate": str(bd["overage_rate"]),
            "gst": str(bd["gst"]),
        },
    }
    order = client.order.create(payload)
    logger.info(
        "overage_order_created",
        org_id=org_id,
        order_id=order.get("id"),
        amount_paise=bd["amount_paise"],
        overage_minutes=bd["overage_minutes"],
    )
    return bd, order

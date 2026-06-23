"""Demonstrate how a clinic is billed for voice-minute OVERAGE via Razorpay.

Scenario (default): a Solo clinic (Rs 1,999/mo, 100 included minutes) that used
1000 minutes in the cycle → 900 overage minutes × Rs 5 = Rs 4,500 + 18% GST (Rs 810)
= Rs 5,310 charged. The script prints the itemised bill and creates a real
Razorpay ORDER (an order is a charge INTENT — no money moves until paid), so you
can see it in the Razorpay dashboard and understand per-minute overage billing.

Usage:
    python -m scripts.generate_fake_bill                 # solo, 1000 min
    python -m scripts.generate_fake_bill clinic 2500     # any plan + minutes
    python -m scripts.generate_fake_bill solo 1000 --dry # math only, no Razorpay

Reads RAZORPAY_KEY_ID/SECRET from the environment (.env). With test keys
(rzp_test_…) this is a sandbox order — safe to run repeatedly.
"""
import sys
import uuid

from backend.services.billing_math import overage_breakdown
from backend.services.overage_billing import create_overage_order, get_razorpay_client


def _rupees(v) -> str:
    return f"Rs {v:,.2f}"


def main(argv: list[str]) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # Windows console is cp1252 by default
    except Exception:
        pass
    args = [a for a in argv if not a.startswith("--")]
    dry = "--dry" in argv
    plan = args[0] if len(args) > 0 else "solo"
    minutes = float(args[1]) if len(args) > 1 else 1000

    bd = overage_breakdown(plan, minutes)
    print("-- Overage bill ------------------------------")
    print(f"  Plan                : {bd['plan']}")
    print(f"  Included minutes    : {bd['included_minutes']}")
    print(f"  Minutes used        : {bd['minutes_used']}")
    print(f"  Overage minutes     : {bd['overage_minutes']}  (used − included)")
    print(f"  Overage rate        : {_rupees(bd['overage_rate'])}/min")
    print(f"  Overage amount      : {_rupees(bd['overage_amount'])}  ({bd['overage_minutes']} × {_rupees(bd['overage_rate'])})")
    print(f"  GST (18%)           : {_rupees(bd['gst'])}")
    print(f"  TOTAL charged       : {_rupees(bd['total_with_gst'])}  = {bd['amount_paise']} paise")
    print("----------------------------------------------")

    if bd["amount_paise"] <= 0:
        print("No overage — nothing to charge.")
        return 0
    if dry:
        print("--dry: skipped Razorpay order creation.")
        return 0

    fake_org_id = str(uuid.uuid4())
    try:
        client = get_razorpay_client()
    except RuntimeError as e:
        print(f"\n[Razorpay not configured: {e}] — math shown above; set keys to create an order.")
        return 0

    _, order = create_overage_order(fake_org_id, plan, minutes, client=client, cycle_label="demo")
    print("\n-- Razorpay order created --------------------")
    print(f"  order_id : {order['id']}")
    print(f"  amount   : {order['amount']} paise  ({_rupees(order['amount'] / 100)})")
    print(f"  status   : {order['status']}")
    print(f"  fake org : {fake_org_id}")
    print("  → Open the Razorpay dashboard → Orders to see this charge intent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

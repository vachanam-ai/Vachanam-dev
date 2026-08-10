"""create_overage_order: correct amount + notes to Razorpay, no zero-amount orders.

Razorpay is mocked — these assert the payload we send (the per-minute overage
math reaches the provider as the right paise total), not the network.
"""
from backend.services.billing_math import GST_WAIVED
from backend.services.overage_billing import create_overage_order

# 600 over-minutes x Rs6/min, +18% GST unless the GST waiver
# waiver is on (GST_WAIVED in billing_math — flip there restores GST here).
_EXPECTED_PAISE = 360000 if GST_WAIVED else 424800


class _FakeOrders:
    def __init__(self):
        self.created = None

    def create(self, payload):
        self.created = payload
        return {"id": "order_FAKE123", "amount": payload["amount"], "status": "created"}


class _FakeClient:
    def __init__(self):
        self.order = _FakeOrders()


def test_create_overage_order_sends_correct_amount_and_notes():
    client = _FakeClient()
    bd, order = create_overage_order("11112222-3333-4444-5555-666677778888", "solo", 1000, client=client)

    # Basic bucket = 400: 1000 used -> 600 over.
    assert bd["overage_minutes"] == 600
    assert bd["amount_paise"] == _EXPECTED_PAISE
    assert client.order.created["amount"] == _EXPECTED_PAISE
    assert client.order.created["currency"] == "INR"
    assert client.order.created["notes"]["type"] == "overage"
    assert client.order.created["notes"]["overage_minutes"] == "600"
    assert order["id"] == "order_FAKE123"


def test_no_order_when_within_bucket():
    client = _FakeClient()
    bd, order = create_overage_order("org", "clinic", 1000, client=client)  # under 1500
    assert bd["overage_minutes"] == 0
    assert order is None
    assert client.order.created is None            # never calls Razorpay for ₹0

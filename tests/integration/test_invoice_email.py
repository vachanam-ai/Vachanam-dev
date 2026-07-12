"""#342: detailed payment invoice/receipt emailed on webhook-confirmed payment.

Receipt mode until VACHANAM_GSTIN is set; tax-invoice mode after. Clinic's own
GSTIN (Settings → Plan & billing) printed for input credit. RULE 8: a mail
failure never un-activates a paid org.
"""
import uuid
from datetime import date

import pytest

from backend.config import settings
from backend.models.schema import Organization
from backend.services.billing_math import subscription_order_breakdown
from backend.services.invoice_email import build_invoice_text, invoice_number

pytestmark = pytest.mark.asyncio


def _bd_clinic_50_over():
    return subscription_order_breakdown("clinic", cycle_minutes_used=1550)


@pytest.mark.asyncio
async def test_receipt_mode_without_our_gstin(monkeypatch):
    monkeypatch.setattr(settings, "vachanam_gstin", "")
    subject, text = build_invoice_text(
        org_name="Sunrise Dental", org_gstin="36ABCDE1234F1Z5", plan="clinic",
        cycle_start=date(2026, 7, 12), cycle_end=date(2026, 8, 11),
        bd=_bd_clinic_50_over(), payment_id="pay_ABC123xyz",
    )
    assert "Payment receipt" in subject
    assert "GST registration in progress" in text
    assert "Sunrise Dental (GSTIN: 36ABCDE1234F1Z5)" in text
    assert "Extra usage: 50 min x Rs 5/min" in text
    assert "12,093.82" in text  # total with GST
    assert "1,844.82" in text   # GST line
    assert "pay_ABC123xyz" in text


@pytest.mark.asyncio
async def test_tax_invoice_mode_with_our_gstin(monkeypatch):
    monkeypatch.setattr(settings, "vachanam_gstin", "36AAACV1234A1Z5")
    subject, text = build_invoice_text(
        org_name="SmileCare", org_gstin=None, plan="solo",
        cycle_start=date(2026, 7, 12), cycle_end=date(2026, 8, 11),
        bd=subscription_order_breakdown("solo"), payment_id="pay_Z9",
    )
    assert "Tax invoice" in subject
    assert "GSTIN: 36AAACV1234A1Z5" in text
    assert "Extra usage:" not in text  # first activation, no overage LINE ITEM
    # (the footer's generic "Extra usage beyond your plan…" note is fine)
    assert "7,078.82" in text  # 5999 × 1.18


def test_invoice_number_unique_and_traceable():
    a = invoice_number(date(2026, 7, 12), "pay_ABC123xyz")
    assert a == "VAC-20260712-123XYZ"


async def test_activation_sends_invoice(db, monkeypatch):
    import backend.services.invoice_email as inv
    from backend.routers.payments import activate_subscription

    sent = {}

    async def fake_send(**kw):
        sent.update(kw)

    monkeypatch.setattr(inv, "send_payment_invoice", fake_send)

    org = Organization(
        name="Invoice Clinic", owner_phone="+919000000070",
        owner_email=f"inv-{uuid.uuid4().hex[:8]}@clinic.in",
        plan="solo", status="trial", gstin="36ABCDE1234F1Z5",
    )
    db.add(org)
    await db.commit()
    await db.refresh(org)

    res = await activate_subscription(db, str(org.id), "solo", f"pay_{uuid.uuid4().hex[:10]}")
    assert res == "activated"
    assert sent["to_email"] == org.owner_email
    assert sent["org_gstin"] == "36ABCDE1234F1Z5"
    assert sent["bd"]["base"] == 5999


async def test_gstin_endpoint_validates_and_saves(db):
    from backend.middleware.auth_middleware import CurrentUser
    from backend.routers.payments import GstinBody, set_gstin

    org = Organization(
        name="Gstin Clinic", owner_phone="+919000000071",
        owner_email=f"g-{uuid.uuid4().hex[:8]}@clinic.in",
        plan="solo", status="active",
    )
    db.add(org)
    await db.commit()
    await db.refresh(org)
    user = CurrentUser(user_id=str(uuid.uuid4()), email="o@x.in", role="org_admin",
                       org_id=str(org.id), branch_ids=[], is_admin=False, jti="j")

    info = await set_gstin(GstinBody(gstin="36abcde1234f1z5"), user, db)
    assert info.gstin == "36ABCDE1234F1Z5"  # uppercased + saved

    with pytest.raises(Exception) as ei:
        await set_gstin(GstinBody(gstin="INVALID-GSTIN!!"), user, db)
    assert getattr(ei.value, "status_code", None) == 422

    info = await set_gstin(GstinBody(gstin=""), user, db)  # clear
    assert info.gstin is None

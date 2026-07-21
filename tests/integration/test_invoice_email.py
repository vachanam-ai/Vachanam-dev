"""#342/#357/#358: payment receipt — Stripe-style HTML card + PDF attachment,
same numbers the order charged. GSTIN removed from all documents (Vinay,
#358 — returns with TD-038 when GST registration lands). RULE 8: a mail
failure never un-activates a paid org.
"""
import uuid
from datetime import date

import pytest

from backend.config import settings
from backend.models.schema import Organization
from backend.services.billing_math import subscription_order_breakdown
from backend.services.invoice_email import (
    build_invoice_html,
    build_invoice_pdf,
    build_invoice_text,
    invoice_number,
)



def _bd_clinic_50_over():
    # Passing a subscription_started_at far outside the 2026-07-17 launch-offer
    # window pins base to the standard clinic price, so these receipt tests
    # don't silently re-break when the offer window logic changes. Amounts are
    # DERIVED from the breakdown (not hardcoded) so a GST_WAIVED flip — the
    # 07-17 change that broke the old "12,093.82 with GST" literals — only
    # changes the numbers, not the contract.
    from datetime import datetime, timedelta, timezone

    return subscription_order_breakdown(
        "clinic", cycle_minutes_used=1550,
        subscription_started_at=datetime.now(timezone.utc) - timedelta(days=365),
    )


def _inr(v: float) -> str:
    return f"{v:,.2f}"


def test_text_receipt_numbers_and_no_gstin():
    bd = _bd_clinic_50_over()
    subject, text = build_invoice_text(
        org_name="Sunrise Dental", plan="clinic",
        cycle_start=date(2026, 7, 12), cycle_end=date(2026, 8, 11),
        bd=bd, payment_id="pay_ABC123xyz",
    )
    assert "receipt" in subject.lower()
    assert _inr(bd["total"]) in text          # amount paid
    if bd["gst"]:
        assert _inr(bd["gst"]) in text        # GST line (only when charged)
    assert "Extra usage" in text and "50 min" in text
    assert "pay_ABC123xyz" in text
    assert "GSTIN" not in text      # #358: removed everywhere
    assert "registration" not in text


def test_html_receipt_card():
    bd = _bd_clinic_50_over()
    html = build_invoice_html(
        org_name="Sunrise Dental", plan="clinic",
        cycle_start=date(2026, 7, 12), cycle_end=date(2026, 8, 11),
        bd=bd, payment_id="pay_ABC123xyz",
    )
    assert "Receipt from Vachanam" in html
    assert _inr(bd["total"]) in html
    if bd["gst"]:
        assert "GST &middot; India (18%)" in html
    assert "Amount paid" in html
    assert "VAC-20260712-123XYZ" in html
    assert "GSTIN" not in html


def test_invoice_number_unique_and_traceable():
    assert invoice_number(date(2026, 7, 12), "pay_ABC123xyz") == "VAC-20260712-123XYZ"


def test_invoice_pdf_builds_without_gstin():
    pdf = build_invoice_pdf(
        org_name="Sunrise Dental", plan="clinic",
        cycle_start=date(2026, 7, 12), cycle_end=date(2026, 8, 11),
        bd=_bd_clinic_50_over(), payment_id="pay_ABC123xyz",
    )
    assert pdf.startswith(b"%PDF") and len(pdf) > 1200


async def test_send_attaches_pdf_and_html(monkeypatch):
    """#357/#358: Resend payload = text + HTML card + base64 PDF named after
    the receipt number; PDF build failure degrades gracefully."""
    import backend.services.invoice_email as ie

    monkeypatch.setattr(settings, "resend_api_key", "re_test", raising=False)

    captured = {}

    class _Resp:
        def raise_for_status(self):
            pass

    class _Client:
        def __init__(self, *a, **k):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def post(self, url, headers=None, json=None):
            captured.update(json)
            return _Resp()

    monkeypatch.setattr(ie.httpx, "AsyncClient", _Client)
    await ie.send_payment_invoice(
        to_email="owner@clinic.in", org_name="Sunrise Dental",
        plan="clinic", cycle_start=date(2026, 7, 12),
        cycle_end=date(2026, 8, 11), bd=_bd_clinic_50_over(),
        payment_id="pay_ABC123xyz",
    )
    assert "Receipt from Vachanam" in captured.get("html", "")
    atts = captured.get("attachments")
    assert atts and atts[0]["filename"] == "VAC-20260712-123XYZ.pdf"
    import base64 as b64
    assert b64.b64decode(atts[0]["content"]).startswith(b"%PDF")

    captured.clear()
    monkeypatch.setattr(ie, "build_invoice_pdf",
                        lambda **k: (_ for _ in ()).throw(RuntimeError("boom")))
    await ie.send_payment_invoice(
        to_email="owner@clinic.in", org_name="Sunrise Dental",
        plan="clinic", cycle_start=date(2026, 7, 12),
        cycle_end=date(2026, 8, 11), bd=_bd_clinic_50_over(),
        payment_id="pay_ABC123xyz",
    )
    assert "attachments" not in captured and captured.get("subject")


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
        plan="solo", status="trial",
    )
    db.add(org)
    await db.commit()
    await db.refresh(org)

    res = await activate_subscription(db, str(org.id), "solo", f"pay_{uuid.uuid4().hex[:10]}")
    assert res == "activated"
    assert sent["to_email"] == org.owner_email
    # First activation = inside the launch-offer window (subscription_started_at
    # None until now) → offer price, not the 5,999 standard (#391 / 2026-07-17).
    from backend.services.billing_math import effective_price

    assert sent["bd"]["base"] == effective_price("solo", None)[0]


async def test_gstin_endpoint_validates_and_saves(db):
    """API kept (#358 removed only the Settings UI field) — a clinic that
    mails us their GSTIN can still have it stored for TD-038 later."""
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
    assert info.gstin == "36ABCDE1234F1Z5"

    with pytest.raises(Exception) as ei:
        await set_gstin(GstinBody(gstin="INVALID-GSTIN!!"), user, db)
    assert getattr(ei.value, "status_code", None) == 422

    info = await set_gstin(GstinBody(gstin=""), user, db)
    assert info.gstin is None

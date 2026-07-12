"""Tests for org_id attribution in payment audit rows.

Original audit finding: payment.verify.success / .fail audit rows had no org_id,
so payments could not be attributed to an organisation.

iter1 #5 update: /verify-payment is UNAUTHENTICATED (the Razorpay HMAC signature
is the auth). It must NOT attribute the audit row to a CLIENT-SUPPLIED
`notes.org_id` — that is forgeable, letting a caller mis-attribute (or hide) a
verification. The order was created server-side (create_order) with
notes.org_id = current_user.org_id, so verify_payment now fetches the order back
from Razorpay and reads ITS trusted notes via _trusted_org_id_for_order().

Tests are pure unit tests — write_audit_row and the Razorpay order fetch are
monkeypatched. No real DB or network call is made.
"""
from __future__ import annotations

import hashlib
import hmac
import uuid
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from backend.config import settings


def _sign(order_id: str, payment_id: str, secret: str) -> str:
    """Produce a valid Razorpay HMAC-SHA256 signature."""
    payload = f"{order_id}|{payment_id}".encode()
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def _mock_request():
    mock_request = MagicMock()
    mock_request.client.host = "127.0.0.1"
    mock_request.headers.get = (
        lambda k, d=None: "python-test/1.0" if k == "user-agent" else d
    )
    return mock_request


def _patch_order_notes(org_id: uuid.UUID | None):
    """Patch the Razorpay order fetch so verify_payment sees a trusted order whose
    server-set notes carry the given org_id. (#354 moved verify_payment onto
    _trusted_order_notes — the full-notes helper — so patch THAT.)"""
    notes = {"org_id": str(org_id)} if org_id is not None else {}

    return patch("backend.routers.payments._trusted_order_notes", lambda order_id: notes)


@pytest.mark.asyncio
async def test_payment_verify_success_audit_has_trusted_org_id() -> None:
    """payment.verify.success audit row carries the org_id from the TRUSTED order."""
    captured_calls: list[dict] = []

    async def fake_write_audit_row(**kwargs: Any) -> None:
        captured_calls.append(kwargs)

    org_id = uuid.uuid4()
    order_id, payment_id, secret = "order_test001", "pay_test001", "test-secret-key"
    signature = _sign(order_id, payment_id, secret)

    with (
        patch.object(settings, "razorpay_key_secret", secret),
        patch.object(settings, "razorpay_key_id", "rzp_test_key"),
        patch("backend.routers.payments._audit_svc.write_audit_row", fake_write_audit_row),
        _patch_order_notes(org_id),
    ):
        from backend.routers.payments import VerifyPaymentRequest, verify_payment

        req = VerifyPaymentRequest(
            razorpay_order_id=order_id,
            razorpay_payment_id=payment_id,
            razorpay_signature=signature,
        )
        response = await verify_payment(request=_mock_request(), req=req)

    assert response.verified is True
    assert len(captured_calls) == 1
    call = captured_calls[0]
    assert call["action"] == "payment.verify.success"
    assert call.get("org_id") == org_id


@pytest.mark.asyncio
async def test_forged_notes_org_id_is_ignored() -> None:
    """iter1 #5: a forged req.notes.org_id must NOT be attributed — the trusted
    order's org_id wins. The attacker passes a victim/decoy org in notes; the audit
    row must carry the real server-set org_id, never the forged one."""
    captured_calls: list[dict] = []

    async def fake_write_audit_row(**kwargs: Any) -> None:
        captured_calls.append(kwargs)

    real_org = uuid.uuid4()
    forged_org = uuid.uuid4()
    order_id, payment_id, secret = "order_forge001", "pay_forge001", "test-secret-key"
    signature = _sign(order_id, payment_id, secret)

    with (
        patch.object(settings, "razorpay_key_secret", secret),
        patch.object(settings, "razorpay_key_id", "rzp_test_key"),
        patch("backend.routers.payments._audit_svc.write_audit_row", fake_write_audit_row),
        _patch_order_notes(real_org),  # trusted order says real_org
    ):
        from backend.routers.payments import VerifyPaymentRequest, verify_payment

        req = VerifyPaymentRequest(
            razorpay_order_id=order_id,
            razorpay_payment_id=payment_id,
            razorpay_signature=signature,
            notes={"org_id": str(forged_org)},  # attacker-supplied
        )
        response = await verify_payment(request=_mock_request(), req=req)

    assert response.verified is True
    assert len(captured_calls) == 1
    call = captured_calls[0]
    assert call.get("org_id") == real_org, "must attribute to the trusted order's org"
    assert call.get("org_id") != forged_org, "forged notes.org_id must be ignored"


@pytest.mark.asyncio
async def test_payment_verify_fail_audit_uses_trusted_org_id() -> None:
    """Even on signature mismatch (400), the audit row uses the trusted order org."""
    captured_calls: list[dict] = []

    async def fake_write_audit_row(**kwargs: Any) -> None:
        captured_calls.append(kwargs)

    org_id = uuid.uuid4()
    order_id, payment_id, secret = "order_fail001", "pay_fail001", "test-secret-key"
    bad_signature = "0" * 64

    from fastapi import HTTPException

    with (
        patch.object(settings, "razorpay_key_secret", secret),
        patch.object(settings, "razorpay_key_id", "rzp_test_key"),
        patch("backend.routers.payments._audit_svc.write_audit_row", fake_write_audit_row),
        _patch_order_notes(org_id),
    ):
        from backend.routers.payments import VerifyPaymentRequest, verify_payment

        req = VerifyPaymentRequest(
            razorpay_order_id=order_id,
            razorpay_payment_id=payment_id,
            razorpay_signature=bad_signature,
            notes={"org_id": str(uuid.uuid4())},  # forged — must be ignored
        )
        with pytest.raises(HTTPException) as exc_info:
            await verify_payment(request=_mock_request(), req=req)

    assert exc_info.value.status_code == 400
    assert len(captured_calls) == 1
    call = captured_calls[0]
    assert call["action"] == "payment.verify.fail"
    assert call.get("org_id") == org_id
    assert call.get("success") is False


@pytest.mark.asyncio
async def test_payment_verify_unknown_order_org_id_is_none() -> None:
    """An order with no resolvable trusted org (unknown/anonymous) → org_id=None,
    passed explicitly so the audit INSERT stores NULL."""
    captured_calls: list[dict] = []

    async def fake_write_audit_row(**kwargs: Any) -> None:
        captured_calls.append(kwargs)

    order_id, payment_id, secret = "order_anon001", "pay_anon001", "test-secret-key"
    signature = _sign(order_id, payment_id, secret)

    with (
        patch.object(settings, "razorpay_key_secret", secret),
        patch.object(settings, "razorpay_key_id", "rzp_test_key"),
        patch("backend.routers.payments._audit_svc.write_audit_row", fake_write_audit_row),
        _patch_order_notes(None),
    ):
        from backend.routers.payments import VerifyPaymentRequest, verify_payment

        req = VerifyPaymentRequest(
            razorpay_order_id=order_id,
            razorpay_payment_id=payment_id,
            razorpay_signature=signature,
        )
        response = await verify_payment(request=_mock_request(), req=req)

    assert response.verified is True
    assert len(captured_calls) == 1
    call = captured_calls[0]
    assert "org_id" in call
    assert call["org_id"] is None


def test_trusted_org_id_fetch_failure_returns_none() -> None:
    """_trusted_org_id_for_order never raises — a fetch failure resolves to None."""
    from backend.routers import payments

    with patch.object(payments, "_get_client", side_effect=RuntimeError("boom")):
        assert payments._trusted_org_id_for_order("order_x") is None
    assert payments._trusted_org_id_for_order("") is None


def test_extract_org_id_invalid_uuid_returns_none() -> None:
    from backend.routers.payments import _extract_org_id

    assert _extract_org_id(None) is None
    assert _extract_org_id({}) is None
    assert _extract_org_id({"org_id": "not-a-uuid"}) is None
    assert _extract_org_id({"org_id": ""}) is None
    assert _extract_org_id({"org_id": None}) is None
    assert _extract_org_id({"other_key": "value"}) is None


def test_extract_org_id_valid_uuid_returns_uuid() -> None:
    from backend.routers.payments import _extract_org_id

    org_id = uuid.uuid4()
    result = _extract_org_id({"org_id": str(org_id)})
    assert result == org_id
    assert isinstance(result, uuid.UUID)

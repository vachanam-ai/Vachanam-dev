"""Tests for org_id attribution in payment audit rows.

Audit finding: payment.verify.success and payment.verify.fail audit rows had no
org_id or branch_id. It was impossible to tell from the audit_log which organisation
made the payment.

Fix: VerifyPaymentRequest now accepts an optional `notes: dict | None` field. If
the caller passes `notes={"org_id": "<uuid>"}`, the verify_payment handler extracts
it and passes it to write_audit_row as org_id=<uuid>. If notes is absent or org_id
is not a valid UUID, org_id=None is passed (acceptable for unauthenticated flows).

Tests are pure unit tests — write_audit_row is monkeypatched. No real DB or Razorpay
call is made.
"""
from __future__ import annotations

import hashlib
import hmac
import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.config import settings


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _sign(order_id: str, payment_id: str, secret: str) -> str:
    """Produce a valid Razorpay HMAC-SHA256 signature."""
    payload = f"{order_id}|{payment_id}".encode()
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


# ──────────────────────────────────────────────────────────────────────────────
# Test 1 — verify_payment success audit row includes org_id from notes
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_payment_verify_success_audit_has_org_id() -> None:
    """payment.verify.success audit row must include org_id when passed in notes.

    The frontend passes notes={"org_id": "<uuid>"} in the VerifyPaymentRequest.
    The handler must extract it and forward it to write_audit_row as org_id=<UUID>.
    """
    captured_calls: list[dict] = []

    async def fake_write_audit_row(**kwargs: Any) -> None:
        captured_calls.append(kwargs)

    org_id = uuid.uuid4()
    order_id = "order_test001"
    payment_id = "pay_test001"
    secret = "test-secret-key"
    signature = _sign(order_id, payment_id, secret)

    # Patch settings to provide the secret and bypass Razorpay client init
    with (
        patch.object(settings, "razorpay_key_secret", secret),
        patch.object(settings, "razorpay_key_id", "rzp_test_key"),
        patch("backend.services.audit_service.write_audit_row", fake_write_audit_row),
        patch("backend.routers.payments._audit_svc.write_audit_row", fake_write_audit_row),
    ):
        from backend.routers.payments import verify_payment, VerifyPaymentRequest
        from starlette.testclient import TestClient as _STC
        from unittest.mock import MagicMock

        # Build a minimal Request mock
        mock_request = MagicMock()
        mock_request.client.host = "127.0.0.1"
        mock_request.headers.get = lambda k, d=None: "python-test/1.0" if k == "user-agent" else d

        req = VerifyPaymentRequest(
            razorpay_order_id=order_id,
            razorpay_payment_id=payment_id,
            razorpay_signature=signature,
            notes={"org_id": str(org_id)},
        )

        response = await verify_payment(request=mock_request, req=req)

    assert response.verified is True
    assert len(captured_calls) == 1, f"Expected 1 audit call, got {len(captured_calls)}"

    call = captured_calls[0]
    assert call["action"] == "payment.verify.success"
    assert call.get("org_id") == org_id, (
        f"Expected org_id={org_id}, got {call.get('org_id')!r}"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Test 2 — verify_payment failure audit row includes org_id from notes
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_payment_verify_fail_audit_has_org_id() -> None:
    """payment.verify.fail audit row must include org_id when passed in notes.

    Even on signature mismatch (400 response), the org_id from notes must
    appear in the audit row so failed payment attempts are attributable.
    """
    captured_calls: list[dict] = []

    async def fake_write_audit_row(**kwargs: Any) -> None:
        captured_calls.append(kwargs)

    org_id = uuid.uuid4()
    order_id = "order_fail001"
    payment_id = "pay_fail001"
    secret = "test-secret-key"
    # Deliberately wrong signature to trigger failure path
    bad_signature = "0" * 64

    from fastapi import HTTPException

    with (
        patch.object(settings, "razorpay_key_secret", secret),
        patch.object(settings, "razorpay_key_id", "rzp_test_key"),
        patch("backend.routers.payments._audit_svc.write_audit_row", fake_write_audit_row),
    ):
        from backend.routers.payments import verify_payment, VerifyPaymentRequest
        from unittest.mock import MagicMock

        mock_request = MagicMock()
        mock_request.client.host = "127.0.0.1"
        mock_request.headers.get = lambda k, d=None: "python-test/1.0" if k == "user-agent" else d

        req = VerifyPaymentRequest(
            razorpay_order_id=order_id,
            razorpay_payment_id=payment_id,
            razorpay_signature=bad_signature,
            notes={"org_id": str(org_id)},
        )

        with pytest.raises(HTTPException) as exc_info:
            await verify_payment(request=mock_request, req=req)

    assert exc_info.value.status_code == 400

    assert len(captured_calls) == 1, f"Expected 1 audit call, got {len(captured_calls)}"
    call = captured_calls[0]
    assert call["action"] == "payment.verify.fail"
    assert call.get("org_id") == org_id, (
        f"Expected org_id={org_id} in failure audit, got {call.get('org_id')!r}"
    )
    assert call.get("success") is False


# ──────────────────────────────────────────────────────────────────────────────
# Test 3 — verify_payment with no notes passes org_id=None (acceptable)
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_payment_verify_success_no_notes_org_id_is_none() -> None:
    """When notes is absent, org_id must be None (not missing — explicitly None).

    Anonymous payment events (trial signup before user exists) are acceptable
    with org_id=None per the audit spec. The key requirement is that org_id is
    passed explicitly (not omitted) so write_audit_row stores NULL in the column
    rather than leaving it out of the INSERT.
    """
    captured_calls: list[dict] = []

    async def fake_write_audit_row(**kwargs: Any) -> None:
        captured_calls.append(kwargs)

    order_id = "order_anon001"
    payment_id = "pay_anon001"
    secret = "test-secret-key"
    signature = _sign(order_id, payment_id, secret)

    with (
        patch.object(settings, "razorpay_key_secret", secret),
        patch.object(settings, "razorpay_key_id", "rzp_test_key"),
        patch("backend.routers.payments._audit_svc.write_audit_row", fake_write_audit_row),
    ):
        from backend.routers.payments import verify_payment, VerifyPaymentRequest
        from unittest.mock import MagicMock

        mock_request = MagicMock()
        mock_request.client.host = "127.0.0.1"
        mock_request.headers.get = lambda k, d=None: "python-test/1.0" if k == "user-agent" else d

        req = VerifyPaymentRequest(
            razorpay_order_id=order_id,
            razorpay_payment_id=payment_id,
            razorpay_signature=signature,
            # notes intentionally absent
        )

        response = await verify_payment(request=mock_request, req=req)

    assert response.verified is True
    assert len(captured_calls) == 1
    call = captured_calls[0]

    # org_id must be explicitly in the kwargs (even if None)
    assert "org_id" in call, (
        "write_audit_row must always receive org_id kwarg (even None) for consistent INSERT"
    )
    assert call["org_id"] is None, (
        f"org_id must be None when notes is absent, got: {call['org_id']!r}"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Test 4 — _extract_org_id handles invalid UUID gracefully
# ──────────────────────────────────────────────────────────────────────────────


def test_extract_org_id_invalid_uuid_returns_none() -> None:
    """_extract_org_id must return None for invalid UUID strings, never raise.

    Callers may pass malformed org_id values (e.g., "not-a-uuid", empty string,
    or an integer). The extractor must be defensive and return None silently.
    """
    from backend.routers.payments import _extract_org_id

    assert _extract_org_id(None) is None
    assert _extract_org_id({}) is None
    assert _extract_org_id({"org_id": "not-a-uuid"}) is None
    assert _extract_org_id({"org_id": ""}) is None
    assert _extract_org_id({"org_id": None}) is None
    assert _extract_org_id({"other_key": "value"}) is None


def test_extract_org_id_valid_uuid_returns_uuid() -> None:
    """_extract_org_id must return a UUID object for a valid UUID string."""
    from backend.routers.payments import _extract_org_id

    org_id = uuid.uuid4()
    result = _extract_org_id({"org_id": str(org_id)})
    assert result == org_id, f"Expected {org_id}, got {result!r}"
    assert isinstance(result, uuid.UUID)

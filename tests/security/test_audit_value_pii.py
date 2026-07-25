"""Security-review fix #5: audit metadata VALUE scrubbing.

The key denylist (TD-022) blocked PII in metadata KEYS but never inspected the
VALUES, so a benign key ({"detail": "call 9666443210"}) could persist a phone /
email / age straight into the append-only AuditLog and the structlog JSON.
write_audit_row now rejects detectable PII in values too, with the same
fail-loud contract — while leaving alphanumeric IDs (Razorpay pay_/order_) and
the login.failure email forensic exception intact.

Pure tests: _contains_pii_value is a pure function, and the raise path in
write_audit_row fires BEFORE any DB write, so no DB/Redis is needed.
"""
import pytest

from backend.services.audit_service import _contains_pii_value, write_audit_row


def test_phone_in_benign_value_key_is_flagged():
    assert _contains_pii_value({"detail": "please call 9666443210 tomorrow"}, "x.y") == "detail"


def test_email_in_value_is_flagged():
    assert _contains_pii_value({"note": "reach priya@example.com"}, "x.y") == "note"


def test_age_in_value_is_flagged():
    assert _contains_pii_value({"note": "patient is 60 years old"}, "x.y") == "note"


def test_alphanumeric_ids_are_not_flagged():
    # Razorpay-style ids carry digit runs but no phone/email/age — must pass so
    # real payment-audit rows are never rejected (5+-digit run is ignored).
    assert _contains_pii_value({"order_id": "order_ABc12345", "payment_id": "pay_9x8y7z6a5b4"}, "x.y") is None


def test_non_string_values_are_ignored():
    assert _contains_pii_value({"count": 5, "ok": True, "ratio": 1.5}, "x.y") is None


def test_login_failure_email_value_exception_preserved():
    # spec §8.2: the attempted email is forensic, allowed under user.login.failure.
    assert _contains_pii_value({"email": "attacker@evil.com"}, "user.login.failure") is None


@pytest.mark.asyncio
async def test_write_audit_row_rejects_phone_in_value():
    with pytest.raises(ValueError, match="detectable PII"):
        await write_audit_row(action="test.value_pii", metadata={"detail": "call 9666443210"})


@pytest.mark.asyncio
async def test_write_audit_row_rejects_email_in_value():
    with pytest.raises(ValueError, match="detectable PII"):
        await write_audit_row(action="test.value_pii", metadata={"freetext": "mail me me@x.com"})

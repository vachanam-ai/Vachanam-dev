"""RED tests for Phase 4.5 Task 6 -- audit_log + @audit decorator.

These tests are the SPEC for the implementer (backend-engineer, Task 7).
They are committed RED -- backend-engineer makes them GREEN by creating
`backend/services/audit_service.py` with: `audit()` decorator,
`write_audit_row()` async helper, `PII_DENYLIST` constant, then wiring
`@audit` onto sensitive routes per spec section 8.

Per tester.md rule 1: failing test FIRST is the deliverable.
Per tester.md rule 7: negative tests for every error path.
Per tester.md rule 9: real DB + real Redis -- uses `db` and `redis` fixtures.
Per tester.md rule 5: no hardcoded URLs, phones, or secrets.

------------------------------------------------------------------------
Spec section 8 -- what the implementer (Task 7) must build to turn these GREEN:

1. Create `backend/services/audit_service.py` with:
   a. `PII_DENYLIST: set[str]` -- keys blocked from metadata_json.
      Blocked words: phone, name, email, address, complaint, symptom.
      Partial match: "patient_phone" contains "phone" -> blocked.
      Exception: login.failure action is allowed to include "email" key
      (spec section 8.2 exception -- attempted email is valuable for forensics).
   b. `async def write_audit_row(
          action: str,
          resource_type: str | None = None,
          resource_id: str | None = None,
          user_id: uuid.UUID | None = None,
          branch_id: uuid.UUID | None = None,
          org_id: uuid.UUID | None = None,
          ip_address: str | None = None,
          user_agent: str | None = None,
          metadata: dict | None = None,
          success: bool = True,
      ) -> None`
      Validates metadata keys against PII_DENYLIST (raises ValueError
      if any key contains a denylist word, unless action is login.failure
      and the key is "email"). Then inserts AuditLog row via
      AsyncSessionLocal.
   c. `def audit(action: str, resource_type: str | None = None)`
      Decorator for route handlers. After the handler executes:
      - Extracts user_id from CurrentUser (if present).
      - Extracts ip_address from request.client.host.
      - Extracts user_agent from request headers.
      - Calls write_audit_row as a BackgroundTask (so audit failure
        does NOT block the user response -- spec section 8.5).
      - On audit write failure: logs via structlog.error, never raises.

2. Wire `@audit` decorator (or Depends()-based equivalent) onto:
   - POST /auth/google -> "user.login.success" (on success),
     "user.login.failure" (on failure)
   - PATCH /queue/{branch_id}/token/{token_id}/attend -> "token.attend"
   - PATCH /queue/{branch_id}/token/{token_id}/no-show -> "token.no_show"
   - POST /api/verify-payment -> "payment.verify.success" (on success),
     "payment.verify.fail" (on failure)

3. Audit failure MUST NOT block user requests (spec section 8.5).
   If write_audit_row raises, the user still gets their 200/201/etc.

If the implementer changes any of these test files to make them pass
(weakening an assertion, lowering N, marking skip), security-engineer
review (Task 7 reviewer) MUST reject and re-dispatch.
------------------------------------------------------------------------
"""
import subprocess
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
import jwt
from sqlalchemy import select

from backend.config import settings
from backend.models.schema import AuditLog


# ======================================================================
# Test infrastructure
# ======================================================================

def _make_jwt(
    user_id: str | None = None,
    email: str = "audit-test@vachanam.in",
    role: str = "receptionist",
    org_id: str | None = None,
    branch_ids: list[str] | None = None,
    is_admin: bool = False,
) -> str:
    """Mint a Vachanam-signed JWT for audit tests."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id or str(uuid.uuid4()),
        "email": email,
        "role": role,
        "org_id": org_id or str(uuid.uuid4()),
        "branch_ids": branch_ids or [str(uuid.uuid4())],
        "is_admin": is_admin,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=settings.jwt_expire_hours)).timestamp()),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def _decode_jwt(token: str) -> dict:
    """Decode without verification (to read sub claim)."""
    return jwt.decode(
        token, settings.jwt_secret, algorithms=["HS256"],
        options={"verify_exp": False},
    )


@pytest_asyncio.fixture
async def client(db, redis):
    """ASGI httpx client with real DB + real Redis.

    Depends on `db` (creates/drops all tables per test) and `redis`
    (flushes between tests). Per tester.md rule 9: real services, no fakes.
    """
    from backend.main import app

    transport = httpx.ASGITransport(app=app, client=("testclient", 123))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


# ======================================================================
# Group 1 -- Successful Google login writes audit_log row
# Spec section 8.1: user.login.success
# ======================================================================


async def test_successful_google_login_writes_audit_log_row(client, db, monkeypatch):
    """POST /auth/google with a mock-verified Google token must write
    an audit_log row with action='user.login.success', the correct
    user_id, an IP address, and success=True.

    Setup: monkeypatch google.oauth2.id_token.verify_oauth2_token to
    return a fake info dict. Pre-seed a User row so login succeeds.
    """
    from backend.models.schema import Organization, User

    # Seed org + user so login finds the user
    test_email = "audit-login-ok@vachanam.in"
    test_google_sub = f"google-sub-{uuid.uuid4()}"
    org = Organization(
        name="Audit Test Org",
        owner_phone="+910000000001",
        owner_email=f"owner-{uuid.uuid4()}@vachanam.in",
        plan="solo",
    )
    db.add(org)
    await db.flush()

    user = User(
        org_id=org.id,
        email=test_email,
        name="Audit Tester",
        role="org_admin",
        google_sub=test_google_sub,
        branch_ids=[],
    )
    db.add(user)
    await db.commit()
    user_id = user.id

    # Monkeypatch Google ID token verification to succeed
    fake_info = {
        "sub": test_google_sub,
        "email": test_email,
        "name": "Audit Tester",
        "aud": "fake-client-id",
    }
    monkeypatch.setattr(settings, "google_oauth_client_id", "fake-client-id")
    monkeypatch.setattr(
        "backend.routers.auth.google_id_token.verify_oauth2_token",
        lambda *args, **kwargs: fake_info,
    )

    r = await client.post("/auth/google", json={"id_token": "valid.mock.token"})
    assert r.status_code == 200, f"Login must succeed (got {r.status_code}): {r.text}"

    # Query audit_log for the login row
    result = await db.execute(
        select(AuditLog).where(
            AuditLog.action == "user.login.success",
            AuditLog.user_id == user_id,
        )
    )
    row = result.scalar_one_or_none()

    assert row is not None, (
        "No audit_log row with action='user.login.success' found after "
        "successful Google login. @audit decorator must be wired on POST /auth/google."
    )
    assert row.success is True, f"success must be True for successful login (got {row.success})"
    assert row.ip_address is not None, "ip_address must be captured from request.client.host"
    assert row.user_id == user_id, f"user_id mismatch: expected {user_id}, got {row.user_id}"


# ======================================================================
# Group 2 -- Failed login writes audit_log row with success=False
# Spec section 8.1: user.login.failure
# ======================================================================


async def test_failed_google_login_writes_audit_log_row(client, db, monkeypatch):
    """POST /auth/google with a junk token (real verify_oauth2_token raises
    ValueError) must write an audit_log row with action='user.login.failure',
    success=False, and metadata_json containing the attempted email.

    Per spec section 8.2 exception: login.failure is ALLOWED to store
    attempted email in metadata (forensics value outweighs PII concern).
    """
    monkeypatch.setattr(
        settings, "google_oauth_client_id",
        "fake-client-id-for-test.apps.googleusercontent.com",
    )

    # Hermetic: real verify_oauth2_token fetches Google certs over the network
    # BEFORE decoding (flaky/blocked in CI). Simulate verification failure.
    def _raise_invalid(*args: object, **kwargs: object) -> None:
        raise ValueError("Invalid token signature (test stub)")

    monkeypatch.setattr(
        "backend.routers.auth.google_id_token.verify_oauth2_token",
        _raise_invalid,
    )

    r = await client.post("/auth/google", json={"id_token": "junk.invalid.token"})
    # 401 from Google verification failure -- that's expected
    assert r.status_code in (401, 403, 429), (
        f"Expected auth failure status, got {r.status_code}"
    )

    # Query audit_log for the failure row
    result = await db.execute(
        select(AuditLog).where(AuditLog.action == "user.login.failure")
    )
    row = result.scalar_one_or_none()

    assert row is not None, (
        "No audit_log row with action='user.login.failure' found after "
        "failed Google login. @audit decorator must log failures too."
    )
    assert row.success is False, f"success must be False for failed login (got {row.success})"
    assert row.ip_address is not None, "ip_address must be captured even on failure"


# ======================================================================
# Group 3 -- PATCH /queue/.../attend writes audit_log row
# Spec section 8.1: token.attend
# ======================================================================


async def test_mark_attended_writes_audit_log_row(client, db, redis):
    """Marking a patient as attended must write an audit_log row with
    action='token.attend', resource_type='token', resource_id matching
    the token's UUID, user_id from the JWT, and branch_id matching.
    """
    from backend.models.schema import Organization, Branch, Doctor, Patient, Token

    # Seed data
    org = Organization(
        name="Audit Queue Org",
        owner_phone="+910000000002",
        owner_email=f"owner-{uuid.uuid4()}@vachanam.in",
        plan="solo",
    )
    db.add(org)
    await db.flush()

    branch = Branch(
        org_id=org.id,
        name="Audit Queue Branch",
        whatsapp_number=f"+91{uuid.uuid4().int % 10**10:010d}",
    )
    db.add(branch)
    await db.flush()

    doctor = Doctor(
        branch_id=branch.id,
        name="Dr. Audit",
        booking_type="token",
    )
    db.add(doctor)
    await db.flush()

    patient = Patient(
        branch_id=branch.id,
        name="Patient Audit",
    )
    db.add(patient)
    await db.flush()

    from datetime import date
    token = Token(
        branch_id=branch.id,
        doctor_id=doctor.id,
        patient_id=patient.id,
        date=date.today(),
        token_number=1,
        source="voice",
        status="confirmed",
    )
    db.add(token)
    await db.commit()

    user_id = str(uuid.uuid4())
    token_jwt = _make_jwt(
        user_id=user_id,
        branch_ids=[str(branch.id)],
    )

    r = await client.patch(
        f"/queue/{branch.id}/token/{token.id}/attend",
        headers={"Authorization": f"Bearer {token_jwt}"},
    )
    assert r.status_code == 200, f"Attend must succeed (got {r.status_code}): {r.text}"

    # Query audit_log
    result = await db.execute(
        select(AuditLog).where(
            AuditLog.action == "token.attend",
        )
    )
    row = result.scalar_one_or_none()

    assert row is not None, (
        "No audit_log row with action='token.attend' found after "
        "PATCH .../attend. @audit('token.attend', resource_type='token') "
        "must be wired on the attend endpoint."
    )
    assert row.resource_type == "token", f"resource_type must be 'token' (got {row.resource_type})"
    assert row.resource_id == str(token.id), (
        f"resource_id must be the token UUID string (expected {token.id}, got {row.resource_id})"
    )
    assert row.user_id == uuid.UUID(user_id), (
        f"user_id must match the JWT sub (expected {user_id}, got {row.user_id})"
    )
    assert row.branch_id == branch.id, (
        f"branch_id must match (expected {branch.id}, got {row.branch_id})"
    )
    assert row.success is True, f"success must be True for successful attend (got {row.success})"


# ======================================================================
# Group 4 -- PATCH /queue/.../no-show writes audit_log row
# Spec section 8.1: token.no_show
# ======================================================================


async def test_mark_no_show_writes_audit_log_row(client, db, redis):
    """Marking a patient as no-show must write an audit_log row with
    action='token.no_show', resource_type='token'.
    """
    from backend.models.schema import Organization, Branch, Doctor, Patient, Token

    org = Organization(
        name="Audit NoShow Org",
        owner_phone="+910000000003",
        owner_email=f"owner-{uuid.uuid4()}@vachanam.in",
        plan="solo",
    )
    db.add(org)
    await db.flush()

    branch = Branch(
        org_id=org.id,
        name="Audit NoShow Branch",
        whatsapp_number=f"+91{uuid.uuid4().int % 10**10:010d}",
    )
    db.add(branch)
    await db.flush()

    doctor = Doctor(
        branch_id=branch.id,
        name="Dr. NoShow",
        booking_type="token",
    )
    db.add(doctor)
    await db.flush()

    patient = Patient(
        branch_id=branch.id,
        name="Patient NoShow",
    )
    db.add(patient)
    await db.flush()

    from datetime import date
    token = Token(
        branch_id=branch.id,
        doctor_id=doctor.id,
        patient_id=patient.id,
        date=date.today(),
        token_number=2,
        source="walk_in",
        status="confirmed",
    )
    db.add(token)
    await db.commit()

    user_id = str(uuid.uuid4())
    token_jwt = _make_jwt(
        user_id=user_id,
        branch_ids=[str(branch.id)],
    )

    r = await client.patch(
        f"/queue/{branch.id}/token/{token.id}/no-show",
        headers={"Authorization": f"Bearer {token_jwt}"},
    )
    assert r.status_code == 200, f"No-show must succeed (got {r.status_code}): {r.text}"

    result = await db.execute(
        select(AuditLog).where(AuditLog.action == "token.no_show")
    )
    row = result.scalar_one_or_none()

    assert row is not None, (
        "No audit_log row with action='token.no_show' found after "
        "PATCH .../no-show. @audit('token.no_show', resource_type='token') "
        "must be wired on the no-show endpoint."
    )
    assert row.resource_type == "token", f"resource_type must be 'token' (got {row.resource_type})"
    assert row.resource_id == str(token.id), (
        f"resource_id must be the token UUID string (expected {token.id}, got {row.resource_id})"
    )
    assert row.success is True


# ======================================================================
# Group 5 -- POST /api/verify-payment success writes audit_log row
# Spec section 8.1: payment.verify.success
# ======================================================================


async def test_verify_payment_success_writes_audit_log_row(client, db, monkeypatch):
    """Successful payment verification (valid HMAC) must write an
    audit_log row with action='payment.verify.success',
    resource_type='payment', resource_id=razorpay_order_id.
    """
    import hashlib
    import hmac as hmac_mod

    # Set a test Razorpay secret
    test_secret = "test_razorpay_secret_for_audit"
    monkeypatch.setattr(settings, "razorpay_key_secret", test_secret)
    monkeypatch.setattr(settings, "razorpay_key_id", "rzp_test_audit")

    order_id = f"order_audit_{uuid.uuid4().hex[:12]}"
    payment_id = f"pay_audit_{uuid.uuid4().hex[:12]}"

    # Compute valid HMAC
    payload_bytes = f"{order_id}|{payment_id}".encode()
    valid_sig = hmac_mod.new(
        test_secret.encode(), payload_bytes, hashlib.sha256,
    ).hexdigest()

    r = await client.post("/api/verify-payment", json={
        "razorpay_order_id": order_id,
        "razorpay_payment_id": payment_id,
        "razorpay_signature": valid_sig,
    })
    assert r.status_code == 200, f"Payment verify must succeed (got {r.status_code}): {r.text}"

    result = await db.execute(
        select(AuditLog).where(AuditLog.action == "payment.verify.success")
    )
    row = result.scalar_one_or_none()

    assert row is not None, (
        "No audit_log row with action='payment.verify.success' found after "
        "successful payment verification. @audit('payment.verify.success', "
        "resource_type='payment') must be wired on POST /api/verify-payment."
    )
    assert row.resource_type == "payment", (
        f"resource_type must be 'payment' (got {row.resource_type})"
    )
    assert row.resource_id == order_id, (
        f"resource_id must be the order_id (expected {order_id}, got {row.resource_id})"
    )
    assert row.success is True


# ======================================================================
# Group 6 -- Signature-mismatch verify-payment writes audit_log row
# Spec section 8.1: payment.verify.fail
# ======================================================================


async def test_verify_payment_signature_mismatch_writes_audit_log_row(client, db, monkeypatch):
    """Payment verification with invalid signature -> 400 response, AND
    an audit_log row with action='payment.verify.fail', success=False.
    Metadata must contain the order_id but NO PII (no patient phone/name).
    """
    test_secret = "test_razorpay_secret_for_audit_fail"
    monkeypatch.setattr(settings, "razorpay_key_secret", test_secret)
    monkeypatch.setattr(settings, "razorpay_key_id", "rzp_test_audit_fail")

    order_id = f"order_audit_fail_{uuid.uuid4().hex[:12]}"
    payment_id = f"pay_audit_fail_{uuid.uuid4().hex[:12]}"

    r = await client.post("/api/verify-payment", json={
        "razorpay_order_id": order_id,
        "razorpay_payment_id": payment_id,
        "razorpay_signature": "definitely_wrong_signature",
    })
    assert r.status_code == 400, (
        f"Signature mismatch must return 400 (got {r.status_code}): {r.text}"
    )

    result = await db.execute(
        select(AuditLog).where(AuditLog.action == "payment.verify.fail")
    )
    row = result.scalar_one_or_none()

    assert row is not None, (
        "No audit_log row with action='payment.verify.fail' found after "
        "signature mismatch. @audit must log failure events too (spec section 8.1)."
    )
    assert row.success is False, f"success must be False for sig mismatch (got {row.success})"
    assert row.resource_type == "payment", (
        f"resource_type must be 'payment' (got {row.resource_type})"
    )

    # Metadata must contain order_id for forensics but NO PII
    if row.metadata_json:
        meta_keys = set(row.metadata_json.keys())
        pii_keys = {k for k in meta_keys if any(
            word in k.lower() for word in ("phone", "name", "address", "complaint", "symptom")
        )}
        assert not pii_keys, (
            f"payment.verify.fail metadata_json contains PII keys: {pii_keys}. "
            "Only non-PII identifiers (order_id, payment_id) are allowed."
        )


# ======================================================================
# Group 7 -- @audit decorator: audit failure does NOT block user request
# Spec section 8.5: background task pattern
# ======================================================================


async def test_audit_failure_does_not_block_user_request(client, db, redis, monkeypatch):
    """If write_audit_row raises (e.g., RuntimeError from DB disconnect),
    the user's request must still succeed (200). The audit failure is
    logged via structlog.error but never propagated to the user.

    We monkeypatch write_audit_row to raise RuntimeError, then hit
    PATCH .../attend and assert the response is still 200.
    """
    from backend.models.schema import Organization, Branch, Doctor, Patient, Token

    org = Organization(
        name="Audit Fail Org",
        owner_phone="+910000000004",
        owner_email=f"owner-{uuid.uuid4()}@vachanam.in",
        plan="solo",
    )
    db.add(org)
    await db.flush()

    branch = Branch(
        org_id=org.id,
        name="Audit Fail Branch",
        whatsapp_number=f"+91{uuid.uuid4().int % 10**10:010d}",
    )
    db.add(branch)
    await db.flush()

    doctor = Doctor(
        branch_id=branch.id,
        name="Dr. AuditFail",
        booking_type="token",
    )
    db.add(doctor)
    await db.flush()

    patient = Patient(
        branch_id=branch.id,
        name="Patient AuditFail",
    )
    db.add(patient)
    await db.flush()

    from datetime import date
    token = Token(
        branch_id=branch.id,
        doctor_id=doctor.id,
        patient_id=patient.id,
        date=date.today(),
        token_number=10,
        source="voice",
        status="confirmed",
    )
    db.add(token)
    await db.commit()

    user_id = str(uuid.uuid4())
    token_jwt = _make_jwt(
        user_id=user_id,
        branch_ids=[str(branch.id)],
    )

    # Monkeypatch write_audit_row to raise -- simulates DB disconnect
    # during audit write. The user's attend request must still succeed.
    async def _broken_audit(*args, **kwargs):
        raise RuntimeError("Simulated audit DB failure")

    monkeypatch.setattr(
        "backend.services.audit_service.write_audit_row",
        _broken_audit,
    )

    r = await client.patch(
        f"/queue/{branch.id}/token/{token.id}/attend",
        headers={"Authorization": f"Bearer {token_jwt}"},
    )
    assert r.status_code == 200, (
        f"User request must succeed (200) even when audit write fails. "
        f"Got {r.status_code}: {r.text}. "
        "The @audit decorator must run write_audit_row as a background task "
        "and catch exceptions (spec section 8.5)."
    )


# ======================================================================
# Group 8 -- PII denylist in metadata_json (closes TD-022)
# ======================================================================


async def test_pii_denylist_rejects_phone_key_in_metadata():
    """write_audit_row(metadata={"phone": "+91..."}) must raise
    ValueError BEFORE any DB insert. The word 'phone' is in PII_DENYLIST.
    """
    from backend.services.audit_service import write_audit_row

    with pytest.raises(ValueError, match="(?i)phone"):
        await write_audit_row(
            action="test.pii_check",
            metadata={"phone": "+919876543210"},
        )


async def test_pii_denylist_rejects_name_key_in_metadata():
    """'name' is in PII_DENYLIST -- must be rejected."""
    from backend.services.audit_service import write_audit_row

    with pytest.raises(ValueError, match="(?i)name"):
        await write_audit_row(
            action="test.pii_check",
            metadata={"name": "Ravi Kumar"},
        )


async def test_pii_denylist_rejects_email_key_in_metadata_for_non_login():
    """'email' is in PII_DENYLIST for non-login actions."""
    from backend.services.audit_service import write_audit_row

    with pytest.raises(ValueError, match="(?i)email"):
        await write_audit_row(
            action="token.attend",
            metadata={"email": "someone@example.com"},
        )


async def test_pii_denylist_rejects_address_key_in_metadata():
    """'address' is in PII_DENYLIST."""
    from backend.services.audit_service import write_audit_row

    with pytest.raises(ValueError, match="(?i)address"):
        await write_audit_row(
            action="test.pii_check",
            metadata={"address": "123 Main St"},
        )


async def test_pii_denylist_rejects_complaint_key_in_metadata():
    """'complaint' is in PII_DENYLIST -- medical PII."""
    from backend.services.audit_service import write_audit_row

    with pytest.raises(ValueError, match="(?i)complaint"):
        await write_audit_row(
            action="test.pii_check",
            metadata={"complaint": "chest pain"},
        )


async def test_pii_denylist_rejects_symptom_key_in_metadata():
    """'symptom' is in PII_DENYLIST -- medical PII."""
    from backend.services.audit_service import write_audit_row

    with pytest.raises(ValueError, match="(?i)symptom"):
        await write_audit_row(
            action="test.pii_check",
            metadata={"symptom": "fever"},
        )


async def test_pii_denylist_partial_match_blocks_patient_phone():
    """'patient_phone' contains 'phone' -- partial match must be blocked."""
    from backend.services.audit_service import write_audit_row

    with pytest.raises(ValueError, match="(?i)phone"):
        await write_audit_row(
            action="test.pii_check",
            metadata={"patient_phone": "+919876543210"},
        )


async def test_pii_denylist_partial_match_blocks_doctor_name():
    """'doctor_name' contains 'name' -- partial match must be blocked."""
    from backend.services.audit_service import write_audit_row

    with pytest.raises(ValueError, match="(?i)name"):
        await write_audit_row(
            action="test.pii_check",
            metadata={"doctor_name": "Dr. Rao"},
        )


async def test_pii_denylist_login_failure_allows_email():
    """Per spec section 8.2 exception: login.failure action IS allowed to store
    'email' in metadata (forensics value for detecting credential-stuffing).
    This must NOT raise ValueError.
    """
    from backend.services.audit_service import write_audit_row

    # This must succeed without raising. If it raises, the implementer
    # has not built the login.failure exception into the denylist logic.
    try:
        await write_audit_row(
            action="user.login.failure",
            metadata={"email": "attacker@evil.com"},
            success=False,
        )
    except ValueError as e:
        pytest.fail(
            f"write_audit_row raised ValueError for email in login.failure "
            f"metadata, but spec section 8.2 explicitly allows this. Error: {e}"
        )


async def test_pii_denylist_constant_is_exported():
    """PII_DENYLIST must be an exported constant so other code can
    reference the denylist for documentation and testing."""
    from backend.services.audit_service import PII_DENYLIST

    assert isinstance(PII_DENYLIST, (set, frozenset, list, tuple)), (
        f"PII_DENYLIST must be a set-like collection, got {type(PII_DENYLIST)}"
    )
    required_words = {"phone", "name", "email", "address", "complaint", "symptom"}
    denylist_lower = {w.lower() for w in PII_DENYLIST}
    missing = required_words - denylist_lower
    assert not missing, (
        f"PII_DENYLIST missing required words: {missing}. "
        f"Current denylist: {PII_DENYLIST}"
    )


# ======================================================================
# Group 9 -- Audit log is append-only at app code level
# ======================================================================


def test_no_update_or_delete_on_audit_log_in_backend_source():
    """Python source under backend/ must never UPDATE or DELETE AuditLog rows.

    This is a static analysis check. The production DB role restriction
    (GRANT INSERT,SELECT only) is Phase 10 (TD-023). At the app code
    level we enforce this now: no code path should call .update() or
    .delete() on AuditLog, and no raw SQL with UPDATE/DELETE audit_log.
    """
    # Use subprocess to grep the backend source tree. The test runs from
    # the repo root; backend/ is relative.
    repo_root = str(
        subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            text=True,
        ).strip()
    )

    # Search for ORM-level update/delete patterns on AuditLog
    patterns = [
        "AuditLog.*\\.update",
        "AuditLog.*\\.delete",
        "\\.delete\\(.*AuditLog",
        "UPDATE audit_log",
        "DELETE FROM audit_log",
        "DELETE.*audit_log",
    ]

    violations = []
    for pattern in patterns:
        result = subprocess.run(
            ["git", "grep", "-n", "-i", "-E", pattern, "--", "backend/"],
            capture_output=True, text=True, cwd=repo_root,
        )
        if result.stdout.strip():
            violations.append(f"Pattern '{pattern}' found:\n{result.stdout.strip()}")

    assert not violations, (
        "Backend source contains UPDATE or DELETE operations on audit_log. "
        "AuditLog is append-only (spec section 8.4). Violations:\n"
        + "\n".join(violations)
    )


# ======================================================================
# Group 10 -- DB user permissions test (DEFERRED)
# ======================================================================


@pytest.mark.skip(
    reason="audit_log GRANT/REVOKE deferred to Phase 10 prod-init per TD-023. "
    "The vachanam_app DB role's INSERT+SELECT-only permission on audit_log "
    "will be enforced by the prod DB init script (devops-engineer). "
    "Testing it requires a separate Postgres role, which is not set up in "
    "the dev/test docker-compose environment. This test placeholder ensures "
    "the requirement is tracked and not forgotten."
)
async def test_db_role_cannot_update_or_delete_audit_log():
    """DEFERRED: Verify the vachanam_app DB role lacks UPDATE and DELETE
    on the audit_log table. Requires Phase 10 prod-init SQL."""
    pass


# ======================================================================
# Group 11 -- Structural: audit_service module exports
# ======================================================================


def test_audit_service_module_exists():
    """backend/services/audit_service.py must exist and be importable."""
    try:
        import backend.services.audit_service  # noqa: F401
    except ImportError:
        pytest.fail(
            "backend/services/audit_service.py does not exist or is not importable. "
            "Task 7 implementer must create it per spec section 8.5."
        )


def test_audit_decorator_is_exported():
    """The `audit` decorator must be importable from audit_service."""
    try:
        from backend.services.audit_service import audit
    except ImportError:
        pytest.fail(
            "backend/services/audit_service.audit not importable. "
            "Task 7 must export `def audit(action: str, resource_type: str | None = None)`."
        )
    assert callable(audit), "audit must be callable (a decorator factory)"


def test_write_audit_row_is_exported():
    """The `write_audit_row` async helper must be importable."""
    import asyncio
    try:
        from backend.services.audit_service import write_audit_row
    except ImportError:
        pytest.fail(
            "backend/services/audit_service.write_audit_row not importable. "
            "Task 7 must export `async def write_audit_row(...)`."
        )
    assert asyncio.iscoroutinefunction(write_audit_row), (
        "write_audit_row must be async (coroutine function)"
    )

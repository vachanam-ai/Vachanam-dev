"""Unit tests for JWT auth middleware.

Per tester.md rule 1: failing test first, then implementation. These tests cover
the pure functions in auth_middleware (no DB, no HTTP). Integration of the full
auth flow against a real DB is in tests/integration/ in a later sprint.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt

from backend.config import settings
from backend.middleware.auth_middleware import create_access_token
from backend.models.schema import User


def _make_user(**overrides) -> User:
    """Build an unsaved User object (no DB) for JWT issuance tests."""
    u = User()
    u.id = overrides.get("id", uuid.uuid4())
    u.email = overrides.get("email", "vinay@example.com")
    u.role = overrides.get("role", "receptionist")
    u.org_id = overrides.get("org_id", uuid.uuid4())
    u.branch_ids = overrides.get("branch_ids", [str(uuid.uuid4())])
    u.is_admin = overrides.get("is_admin", False)
    return u


def test_create_access_token_returns_decodable_jwt():
    user = _make_user()
    token = create_access_token(user)
    assert isinstance(token, str)
    payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    assert payload["sub"] == str(user.id)
    assert payload["email"] == "vinay@example.com"
    assert payload["role"] == "receptionist"
    assert payload["is_admin"] is False


def test_access_token_includes_all_required_claims():
    user = _make_user(
        email="admin@vachanam.in",
        role="super_admin",
        branch_ids=["b1", "b2", "b3"],
        is_admin=True,
    )
    token = create_access_token(user)
    payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    for claim in ("sub", "email", "role", "org_id", "branch_ids", "is_admin", "iat", "exp", "jti"):
        assert claim in payload, f"Missing claim: {claim}"
    assert payload["is_admin"] is True
    assert payload["role"] == "super_admin"
    assert payload["branch_ids"] == ["b1", "b2", "b3"]


def test_access_token_jti_is_unique_per_call():
    """jti must be a fresh UUID per token so revocation targets one token only."""
    user = _make_user()
    t1 = create_access_token(user)
    t2 = create_access_token(user)
    p1 = jwt.decode(t1, settings.jwt_secret, algorithms=["HS256"])
    p2 = jwt.decode(t2, settings.jwt_secret, algorithms=["HS256"])
    assert p1["jti"] != p2["jti"], "Two tokens for same user must have different jti"


def test_access_token_expiration_matches_settings():
    """exp must be `settings.jwt_expire_hours` after iat — no longer, no shorter."""
    user = _make_user()
    before = datetime.now(timezone.utc)
    token = create_access_token(user)
    payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    expected_exp = before + timedelta(hours=settings.jwt_expire_hours)
    actual_exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
    # Allow ±2s for test execution time
    delta = abs((actual_exp - expected_exp).total_seconds())
    assert delta < 2, f"exp drift {delta}s exceeds 2s tolerance"


def test_tampered_token_signature_rejected():
    """Modify any byte of the token → signature mismatch → JWTError on decode."""
    user = _make_user()
    token = create_access_token(user)
    # Flip a character in the signature segment (third . separated section)
    parts = token.split(".")
    tampered_sig = "X" + parts[2][1:] if parts[2][0] != "X" else "Y" + parts[2][1:]
    tampered = f"{parts[0]}.{parts[1]}.{tampered_sig}"
    from jose import JWTError
    with pytest.raises(JWTError):
        jwt.decode(tampered, settings.jwt_secret, algorithms=["HS256"])


def test_expired_token_rejected():
    """Token past exp → jose raises JWTError on decode (ExpiredSignatureError subclass)."""
    user = _make_user()
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "role": user.role,
        "org_id": str(user.org_id),
        "branch_ids": user.branch_ids,
        "is_admin": user.is_admin,
        "iat": int(past.timestamp()) - 3600,
        "exp": int(past.timestamp()),
        "jti": str(uuid.uuid4()),
    }
    expired_token = jwt.encode(payload, settings.jwt_secret, algorithm="HS256")
    from jose import JWTError
    with pytest.raises(JWTError):
        jwt.decode(expired_token, settings.jwt_secret, algorithms=["HS256"])

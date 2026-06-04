"""RED/GREEN tests for Phase 4.5 Task 8 -- JWT lifecycle hardening.

Verifies that the JWT authentication middleware (backend/middleware/auth_middleware.py)
correctly handles all failure modes per spec section 5:
  - Expired token -> 401
  - Tampered signature -> 401
  - Revoked jti -> 401
  - Missing Authorization header -> 401
  - Malformed Bearer header -> 401

These tests should be mostly GREEN (auth_middleware.py already implements
all these checks). If any are RED, the JWT middleware has a gap.

Per spec section 12.1: test_jwt.py verifies expired/tampered/revoked/missing -> 401.
Per tester.md rule 1: failing test FIRST is the deliverable.
Per tester.md rule 7: negative tests for every error path.
Per tester.md rule 5: no hardcoded URLs, phones, or secrets.
Per QUALITY_BAR: no time.sleep; JWT expiry tested via manually constructed past exp claim.
"""
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest_asyncio
from jose import jwt

from backend.config import settings


# ======================================================================
# Test infrastructure
# ======================================================================

# Use a protected route that requires get_current_user but does NOT require
# DB-seeded data to evaluate the JWT layer. The queue endpoint
# /queue/{branch}/today requires authentication. It may return 500 if
# the branch doesn't exist in DB, but the JWT layer runs FIRST and must
# reject bad tokens with 401 BEFORE reaching the handler.
_PROTECTED_ROUTE = "/queue/{branch}/today"


def _make_jwt(
    user_id: str | None = None,
    is_admin: bool = False,
    expired: bool = False,
    branch_ids: list[str] | None = None,
    jti: str | None = None,
    secret: str | None = None,
) -> str:
    """Mint a Vachanam-signed JWT for JWT lifecycle tests.

    Params:
        expired: If True, exp is set 1 hour in the past.
        secret: If provided, sign with this secret instead of settings.jwt_secret
                (used for tampered-signature tests).
        jti: If provided, use this jti (used for revocation tests).
    """
    now = datetime.now(timezone.utc)
    if expired:
        exp = now - timedelta(hours=1)
    else:
        exp = now + timedelta(hours=settings.jwt_expire_hours)
    payload = {
        "sub": user_id or str(uuid.uuid4()),
        "email": "jwt-test@vachanam.in",
        "role": "receptionist",
        "org_id": str(uuid.uuid4()),
        "branch_ids": branch_ids or [str(uuid.uuid4())],
        "is_admin": is_admin,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "jti": jti or str(uuid.uuid4()),
    }
    signing_secret = secret if secret is not None else settings.jwt_secret
    return jwt.encode(payload, signing_secret, algorithm="HS256")


@pytest_asyncio.fixture
async def client(redis):
    """ASGI httpx client for JWT tests.

    Depends on `redis` because:
    1. App lifespan initializes the rate limiter (needs Redis).
    2. JWT revocation check reads from Redis.
    Per tester.md rule 9: real Redis, no fakes.
    """
    from backend.main import app

    transport = httpx.ASGITransport(app=app, client=("testclient", 123))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


# ======================================================================
# Test 1 -- Expired token returns 401
# ======================================================================


async def test_expired_token_returns_401(client):
    """A JWT with exp set 1 hour in the past must be rejected with 401.

    Per spec section 5.4: hard timeout means the backend rejects the token
    regardless of activity. jose.jwt.decode raises ExpiredSignatureError,
    which get_current_user catches and returns 401.
    """
    branch_id = str(uuid.uuid4())
    token = _make_jwt(expired=True, branch_ids=[branch_id])
    r = await client.get(
        f"/queue/{branch_id}/today",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 401, (
        f"Expired JWT must return 401. Got {r.status_code}: {r.text}. "
        "get_current_user must catch JWTError from expired token decode."
    )
    # Response body should indicate the token issue (not a generic 500)
    assert "expired" in r.text.lower() or "invalid" in r.text.lower() or "token" in r.text.lower(), (
        f"401 response for expired token should mention the issue in detail. "
        f"Got body: {r.text!r}"
    )


# ======================================================================
# Test 2 -- Tampered signature returns 401
# ======================================================================


async def test_tampered_signature_returns_401(client):
    """A JWT signed with a DIFFERENT secret (simulating signature tampering)
    must be rejected with 401.

    An attacker who steals a JWT and modifies claims (e.g., sets is_admin=True)
    cannot re-sign with the correct secret, so the signature won't verify.
    """
    branch_id = str(uuid.uuid4())
    # Sign with a wrong secret -- simulates an attacker forging claims
    wrong_secret = "this_is_not_the_real_secret_obviously_fake_key_12345"
    token = _make_jwt(secret=wrong_secret, branch_ids=[branch_id])
    r = await client.get(
        f"/queue/{branch_id}/today",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 401, (
        f"Tampered JWT (wrong signing key) must return 401. Got {r.status_code}: {r.text}. "
        "jose.jwt.decode must reject tokens signed with a different secret."
    )


# ======================================================================
# Test 3 -- Revoked jti returns 401
# ======================================================================


async def test_revoked_jti_returns_401(client, redis):
    """A JWT whose jti has been added to the Redis revocation set must
    be rejected with 401 "Token revoked".

    Per spec section 5.5: POST /auth/logout adds the jti to
    `revoked_jwts:<jti>` in Redis. Subsequent requests with that token
    must be rejected even though the signature and exp are still valid.
    """
    branch_id = str(uuid.uuid4())
    jti = str(uuid.uuid4())
    token = _make_jwt(branch_ids=[branch_id], jti=jti)

    # Pre-seed the revocation entry in Redis (simulating a prior logout)
    await redis.set(f"revoked_jwts:{jti}", "1", ex=3600)

    r = await client.get(
        f"/queue/{branch_id}/today",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 401, (
        f"Revoked JWT (jti in Redis revocation set) must return 401. "
        f"Got {r.status_code}: {r.text}. "
        "get_current_user must check `revoked_jwts:<jti>` in Redis."
    )
    assert "revoked" in r.text.lower() or "invalid" in r.text.lower() or "token" in r.text.lower(), (
        f"401 response for revoked token should indicate revocation. "
        f"Got body: {r.text!r}"
    )


# ======================================================================
# Test 4 -- Missing Authorization header returns 401
# ======================================================================


async def test_missing_authorization_header_returns_401(client):
    """A request to a protected route with NO Authorization header must
    return 401 (or 403 from HTTPBearer auto_error).

    Per spec section 5: all protected routes require
    Authorization: Bearer <jwt>. Without it, the request must be rejected
    immediately.
    """
    branch_id = str(uuid.uuid4())
    r = await client.get(f"/queue/{branch_id}/today")
    assert r.status_code in (401, 403), (
        f"Missing Authorization header on protected route must return 401/403. "
        f"Got {r.status_code}: {r.text}. "
        "HTTPBearer(auto_error=True) must reject requests without credentials."
    )


# ======================================================================
# Test 5 -- Malformed Bearer header returns 401
# ======================================================================


async def test_malformed_bearer_returns_401(client):
    """Authorization header with 'Bearer' but no token (just the word
    'Bearer' followed by nothing, or 'Bearer ') must return 401.

    This catches edge cases where the frontend clears the token but
    leaves the header prefix, or where an attacker sends garbage.
    """
    branch_id = str(uuid.uuid4())

    # Case 1: "Bearer " with empty token
    r = await client.get(
        f"/queue/{branch_id}/today",
        headers={"Authorization": "Bearer "},
    )
    assert r.status_code in (401, 403, 422), (
        f"Malformed Bearer (empty token) must return 401/403/422. "
        f"Got {r.status_code}: {r.text}."
    )

    # Case 2: "Bearer not.a.jwt.at.all" (garbage that is not valid JWT structure)
    r2 = await client.get(
        f"/queue/{branch_id}/today",
        headers={"Authorization": "Bearer not-a-jwt-at-all"},
    )
    assert r2.status_code == 401, (
        f"Malformed Bearer (garbage token) must return 401. "
        f"Got {r2.status_code}: {r2.text}. "
        "jose.jwt.decode must reject non-JWT strings."
    )

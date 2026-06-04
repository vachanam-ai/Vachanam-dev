"""RED tests for Phase 4.5 Task 8 -- require_admin dependency enforcement.

These tests verify that the `require_admin` dependency (already implemented in
backend/middleware/auth_middleware.py) correctly gates admin-only routes:
  - Non-admin JWT -> 403
  - Admin JWT (is_admin=True) -> 200
  - No JWT -> 401
  - Expired admin JWT -> 401

INTENTIONALLY RED until Task 9 creates a `/admin/ping` route gated by
`require_admin`. The `require_admin` dependency already exists -- it just
needs a route to mount it on.

Per spec section 12.1: test_admin_only.py verifies non-admin JWT hitting
/admin/* returns 403.

Per tester.md rule 1: failing test FIRST is the deliverable.
Per tester.md rule 7: negative tests for every error path (401, 403).
Per tester.md rule 5: no hardcoded URLs, phones, or secrets.

If the implementer changes any of these test files to make them pass
(weakening an assertion, lowering N, marking skip), security-engineer
review MUST reject and re-dispatch.
------------------------------------------------------------------------
SPEC TO IMPLEMENTER (Task 9):
  - Create backend/routers/admin.py with a minimal `GET /admin/ping` route
  - Guard it with `Depends(require_admin)` from backend/middleware/auth_middleware
  - Register it in backend/main.py: `app.include_router(admin_router.router, prefix="/admin", tags=["admin"])`
  - require_admin already exists and works -- just wire it to a route
  - All 4 tests below use Authorization: Bearer <jwt_with_is_admin_claim>
------------------------------------------------------------------------
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


def _make_jwt(
    user_id: str | None = None,
    is_admin: bool = False,
    expired: bool = False,
) -> str:
    """Mint a Vachanam-signed JWT for admin tests.

    Set is_admin=True to simulate an admin user (Vinay).
    Set expired=True to simulate an expired token.
    """
    now = datetime.now(timezone.utc)
    if expired:
        exp = now - timedelta(hours=1)
    else:
        exp = now + timedelta(hours=settings.jwt_expire_hours)
    payload = {
        "sub": user_id or str(uuid.uuid4()),
        "email": "admin-test@vachanam.in",
        "role": "super_admin" if is_admin else "receptionist",
        "org_id": str(uuid.uuid4()),
        "branch_ids": [str(uuid.uuid4())],
        "is_admin": is_admin,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


@pytest_asyncio.fixture
async def client(redis):
    """ASGI httpx client for admin tests.

    Depends on `redis` because app lifespan initializes the rate limiter.
    """
    from backend.main import app

    transport = httpx.ASGITransport(app=app, client=("testclient", 123))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


# ======================================================================
# Test 1 -- Non-admin JWT on /admin/ping returns 403
# ======================================================================


async def test_non_admin_jwt_returns_403(client):
    """A valid JWT with is_admin=False hitting GET /admin/ping must
    return 403 "Admin access required".

    The require_admin dependency checks the is_admin claim and raises
    HTTPException(403) if False. This is the primary guard -- a
    receptionist or org_admin who is not Vinay must never reach admin
    endpoints.
    """
    token = _make_jwt(is_admin=False)
    r = await client.get(
        "/admin/ping",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403, (
        f"Non-admin JWT on /admin/ping must return 403. Got {r.status_code}: {r.text}. "
        "require_admin dependency must be wired on this route."
    )


# ======================================================================
# Test 2 -- Admin JWT on /admin/ping returns 200
# ======================================================================


async def test_admin_jwt_returns_200(client):
    """A valid JWT with is_admin=True hitting GET /admin/ping must
    return 200.

    This is the happy path -- Vinay (the only admin) hits the admin
    endpoint and gets through.
    """
    token = _make_jwt(is_admin=True)
    r = await client.get(
        "/admin/ping",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, (
        f"Admin JWT on /admin/ping must return 200. Got {r.status_code}: {r.text}. "
        "Either the route doesn't exist or require_admin is rejecting admin users."
    )


# ======================================================================
# Test 3 -- No JWT on /admin/ping returns 401
# ======================================================================


async def test_no_jwt_returns_401(client):
    """GET /admin/ping without any Authorization header must return 401.

    The HTTPBearer(auto_error=True) dependency in get_current_user will
    raise 401/403 when no credentials are provided. The exact status code
    depends on FastAPI/Starlette version; both 401 and 403 are acceptable
    for "no credentials", but 401 is canonical.
    """
    r = await client.get("/admin/ping")
    assert r.status_code in (401, 403), (
        f"No JWT on /admin/ping must return 401 or 403. Got {r.status_code}: {r.text}. "
        "The admin route must require authentication (get_current_user dependency)."
    )


# ======================================================================
# Test 4 -- Expired admin JWT on /admin/ping returns 401
# ======================================================================


async def test_expired_admin_jwt_returns_401(client):
    """An expired JWT (even with is_admin=True) hitting GET /admin/ping
    must return 401 "Invalid or expired token".

    Admin status does not override token expiration. The JWT decode step
    happens BEFORE the is_admin check, so expired tokens are rejected
    regardless of claims.
    """
    token = _make_jwt(is_admin=True, expired=True)
    r = await client.get(
        "/admin/ping",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 401, (
        f"Expired admin JWT on /admin/ping must return 401. Got {r.status_code}: {r.text}. "
        "Token expiration must be enforced BEFORE admin claim check."
    )

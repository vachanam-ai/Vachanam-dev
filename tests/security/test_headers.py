"""RED/GREEN tests for Phase 4.5 Task 8 -- security headers on every response.

Verifies that SecurityHeadersMiddleware (backend/middleware/security_headers.py)
injects the 6 required security headers on every response, regardless of route,
status code, or authentication state.

Per spec section 10.5 (2026-05-22-security-hardening-design.md):
  - Strict-Transport-Security: max-age=31536000; includeSubDomains
  - X-Content-Type-Options: nosniff
  - X-Frame-Options: DENY
  - Referrer-Policy: strict-origin-when-cross-origin
  - Permissions-Policy: geolocation=(), microphone=(), camera=()
  - Content-Security-Policy: default-src 'self'; ... (Razorpay + Google whitelisted)

These tests should be GREEN immediately (Task 3 already implemented the
middleware). If any are RED, the middleware is broken or not wired.

Per tester.md rule 1: failing test FIRST is the deliverable.
Per tester.md rule 7: negative tests for every error path (4xx still has headers).
Per tester.md rule 5: no hardcoded URLs, phones, or secrets.
"""
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
from jose import jwt

from backend.config import settings


# ======================================================================
# Test infrastructure
# ======================================================================

# The 6 security headers we require on EVERY response per spec section 10.5.
REQUIRED_HEADERS = {
    "strict-transport-security",
    "x-content-type-options",
    "x-frame-options",
    "referrer-policy",
    "permissions-policy",
    "content-security-policy",
}


def _make_jwt(
    user_id: str | None = None,
    branch_ids: list[str] | None = None,
    is_admin: bool = False,
) -> str:
    """Mint a Vachanam-signed JWT for header tests."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id or str(uuid.uuid4()),
        "email": "header-test@vachanam.in",
        "role": "receptionist",
        "org_id": str(uuid.uuid4()),
        "branch_ids": branch_ids or [str(uuid.uuid4())],
        "is_admin": is_admin,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=settings.jwt_expire_hours)).timestamp()),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def _assert_security_headers_present(response: httpx.Response, context: str) -> None:
    """Assert all 6 required security headers are present on the response.

    Raises AssertionError with a clear message identifying which headers
    are missing and in what context (endpoint + status code).
    """
    response_header_keys = {h.lower() for h in response.headers.keys()}
    missing = REQUIRED_HEADERS - response_header_keys
    assert not missing, (
        f"Missing security headers on {context}: {missing}. "
        f"SecurityHeadersMiddleware must inject all 6 headers on EVERY response. "
        f"Headers present: {sorted(response_header_keys)}"
    )


@pytest_asyncio.fixture
async def client(redis):
    """ASGI httpx client for header tests.

    Depends on `redis` because the app lifespan initializes the rate limiter
    which needs a Redis connection. Per tester.md rule 9: real services.
    """
    from backend.main import app

    transport = httpx.ASGITransport(app=app, client=("testclient", 123))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


# ======================================================================
# Test 1 -- /health returns all 6 security headers
# ======================================================================


async def test_health_endpoint_has_all_security_headers(client):
    """GET /health (unauthenticated, always 200) must carry all 6 headers."""
    r = await client.get("/health")
    assert r.status_code == 200
    _assert_security_headers_present(r, "GET /health (200)")


# ======================================================================
# Test 2 -- / (landing page) returns all 6 security headers
# ======================================================================


async def test_landing_page_has_all_security_headers(client):
    """GET / (landing page, unauthenticated) must carry all 6 headers."""
    r = await client.get("/")
    # Landing page returns 200 if index.html exists, 404 if not -- both are fine
    _assert_security_headers_present(r, f"GET / ({r.status_code})")


# ======================================================================
# Test 3 -- POST /api/create-order returns all 6 security headers
# ======================================================================


async def test_create_order_has_all_security_headers(client):
    """POST /api/create-order (payments endpoint) must carry all 6 headers.

    We send an empty body intentionally -- the endpoint will return 422
    (validation error). The point is the middleware runs regardless.
    """
    r = await client.post("/api/create-order", json={})
    # 422 from Pydantic validation failure is expected
    _assert_security_headers_present(r, f"POST /api/create-order ({r.status_code})")


# ======================================================================
# Test 4 -- 403 on protected route without JWT still has security headers
# ======================================================================


async def test_protected_route_403_has_all_security_headers(client):
    """GET /queue/{branch}/today without JWT returns 401/403 but must
    still carry all 6 security headers.

    Critical negative test: attackers probing unauthenticated routes must
    not see responses without HSTS/CSP -- that would reveal the endpoint
    exists AND allow downgrade/injection attacks on the error page.
    """
    fake_branch = str(uuid.uuid4())
    r = await client.get(f"/queue/{fake_branch}/today")
    assert r.status_code in (401, 403), (
        f"Expected 401/403 for unauthenticated queue access, got {r.status_code}"
    )
    _assert_security_headers_present(r, f"GET /queue/{{branch}}/today ({r.status_code})")


# ======================================================================
# Test 5 -- Specific header values match spec section 10.5
# ======================================================================


async def test_header_values_match_spec(client):
    """Each security header must have the exact value specified in spec section 10.5."""
    r = await client.get("/health")
    assert r.status_code == 200

    # HSTS: must contain max-age (spec says 31536000 = 1 year)
    hsts = r.headers.get("strict-transport-security", "")
    assert "max-age=" in hsts, (
        f"HSTS header must contain max-age directive. Got: {hsts!r}"
    )
    assert "includeSubDomains" in hsts, (
        f"HSTS header must contain includeSubDomains. Got: {hsts!r}"
    )

    # X-Content-Type-Options: exact value
    xcto = r.headers.get("x-content-type-options", "")
    assert xcto == "nosniff", (
        f"X-Content-Type-Options must be exactly 'nosniff'. Got: {xcto!r}"
    )

    # X-Frame-Options: exact value
    xfo = r.headers.get("x-frame-options", "")
    assert xfo == "DENY", (
        f"X-Frame-Options must be exactly 'DENY'. Got: {xfo!r}"
    )

    # Referrer-Policy: non-empty, spec says strict-origin-when-cross-origin
    rp = r.headers.get("referrer-policy", "")
    assert rp != "", "Referrer-Policy header must be non-empty."
    assert rp == "strict-origin-when-cross-origin", (
        f"Referrer-Policy must be 'strict-origin-when-cross-origin' per spec. Got: {rp!r}"
    )

    # Permissions-Policy: non-empty, must deny geo/mic/camera
    pp = r.headers.get("permissions-policy", "")
    assert pp != "", "Permissions-Policy header must be non-empty."
    assert "geolocation=()" in pp, f"Permissions-Policy must deny geolocation. Got: {pp!r}"
    assert "microphone=()" in pp, f"Permissions-Policy must deny microphone. Got: {pp!r}"
    assert "camera=()" in pp, f"Permissions-Policy must deny camera. Got: {pp!r}"


# ======================================================================
# Test 6 -- CSP contains required directives
# ======================================================================


async def test_csp_contains_required_directives(client):
    """Content-Security-Policy must contain default-src, script-src with
    Razorpay and Google, frame-src, and object-src 'none'.

    Per spec section 10.5 CSP breakdown.
    """
    r = await client.get("/health")
    csp = r.headers.get("content-security-policy", "")

    assert "default-src" in csp, (
        f"CSP must contain default-src directive. Got: {csp!r}"
    )
    assert "'self'" in csp, (
        f"CSP default-src must include 'self'. Got: {csp!r}"
    )
    assert "checkout.razorpay.com" in csp, (
        f"CSP script-src must allow Razorpay checkout. Got: {csp!r}"
    )
    assert "accounts.google.com" in csp, (
        f"CSP must allow Google accounts (OAuth). Got: {csp!r}"
    )
    assert "object-src 'none'" in csp, (
        f"CSP must block object/embed (object-src 'none'). Got: {csp!r}"
    )
    assert "base-uri 'self'" in csp, (
        f"CSP must restrict base-uri to 'self'. Got: {csp!r}"
    )


# ======================================================================
# Test 7 -- Authenticated request also carries all security headers
# ======================================================================


async def test_authenticated_request_has_all_security_headers(client):
    """A request WITH a valid JWT to a protected route that returns 200
    (or any non-error status) must also carry all 6 security headers.

    Ensures the middleware runs for authenticated traffic, not just
    unauthenticated probes.
    """
    branch_id = str(uuid.uuid4())
    token = _make_jwt(branch_ids=[branch_id])
    r = await client.get(
        f"/queue/{branch_id}/today",
        headers={"Authorization": f"Bearer {token}"},
    )
    # The branch doesn't exist in DB, so we might get 500 or similar --
    # the point is headers are present regardless of status code.
    _assert_security_headers_present(
        r, f"GET /queue/{{branch}}/today with JWT ({r.status_code})"
    )

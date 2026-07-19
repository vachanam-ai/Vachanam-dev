"""RED/GREEN tests for Phase 4.5 Task 8 -- CORS configuration.

Verifies that CORSMiddleware in backend/main.py enforces the exact-origin
allowlist per spec section 10.6:
  - Allowed: settings.frontend_url (production: https://app.vachanam.in),
    plus http://localhost:3000 and http://localhost:5173 in dev mode.
  - Blocked: any unlisted origin (e.g. https://evil.com)
  - Wildcard '*' NEVER appears when allow_credentials=True
  - Allowed methods: GET, POST, PATCH, DELETE, OPTIONS
  - Allowed headers: Authorization, Content-Type

These tests should be GREEN immediately (Task 3 already wired CORSMiddleware
in main.py). If any are RED, the CORS config is wrong or missing.

Per tester.md rule 1: failing test FIRST is the deliverable.
Per tester.md rule 7: negative tests (evil origin blocked).
Per tester.md rule 5: no hardcoded URLs, phones, or secrets.
"""
import httpx
import pytest_asyncio

from backend.config import settings


# ======================================================================
# Test infrastructure
# ======================================================================


@pytest_asyncio.fixture
async def client(redis):
    """ASGI httpx client for CORS tests.

    Depends on `redis` because app lifespan initializes the rate limiter.
    """
    from backend.main import app

    transport = httpx.ASGITransport(app=app, client=("testclient", 123))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


# ======================================================================
# Test 1 -- Preflight from allowed origin returns ACAO header
# ======================================================================


async def test_preflight_from_allowed_origin_returns_acao(client):
    """OPTIONS preflight from settings.frontend_url (the configured
    allowed origin) must return Access-Control-Allow-Origin matching
    that exact origin.

    This is the happy path: the React PWA at the configured frontend_url
    sends a preflight before calling our API.
    """
    allowed_origin = settings.frontend_url
    r = await client.options(
        "/health",
        headers={
            "Origin": allowed_origin,
            "Access-Control-Request-Method": "GET",
        },
    )
    acao = r.headers.get("access-control-allow-origin", "")
    assert acao == allowed_origin, (
        f"Preflight from allowed origin {allowed_origin!r} must return "
        f"Access-Control-Allow-Origin: {allowed_origin!r}. Got: {acao!r}. "
        "CORSMiddleware is either missing or not configured with the correct "
        "allow_origins list."
    )


# ======================================================================
# Test 2 -- Preflight from evil origin is blocked
# ======================================================================


async def test_preflight_from_evil_origin_blocked(client):
    """OPTIONS preflight from https://evil.com must NOT return an
    Access-Control-Allow-Origin header (or must not match evil.com).

    This prevents malicious sites from making credentialed cross-origin
    requests to our API.
    """
    evil_origin = "https://evil.com"
    r = await client.options(
        "/health",
        headers={
            "Origin": evil_origin,
            "Access-Control-Request-Method": "GET",
        },
    )
    acao = r.headers.get("access-control-allow-origin", "")
    assert acao != evil_origin, (
        f"Preflight from evil origin {evil_origin!r} returned "
        f"Access-Control-Allow-Origin: {acao!r}. This is a security hole: "
        "any malicious site can make credentialed requests to our API. "
        "CORSMiddleware must use exact origin list, not wildcard."
    )
    # Also ensure wildcard is not used
    assert acao != "*", (
        "Access-Control-Allow-Origin is '*' (wildcard). This is forbidden "
        "when allow_credentials=True per CORS spec. The browser will reject "
        "it, but the intent is still wrong."
    )


# ======================================================================
# Test 3 -- Wildcard '*' NEVER appears as ACAO value
# ======================================================================


async def test_wildcard_never_used_with_credentials(client):
    """When allow_credentials=True, the CORS spec forbids
    Access-Control-Allow-Origin: *. Verify no endpoint returns it.

    Test with a simple GET to /health with Origin header set.
    """
    r = await client.get(
        "/health",
        headers={"Origin": settings.frontend_url},
    )
    acao = r.headers.get("access-control-allow-origin", "")
    # If ACAO is present, it must be the exact origin, never wildcard
    if acao:
        assert acao != "*", (
            "Access-Control-Allow-Origin is '*'. When allow_credentials=True, "
            "browsers reject wildcard ACAO. Spec section 10.6 explicitly forbids "
            "wildcard origins."
        )
        assert acao == settings.frontend_url, (
            f"Access-Control-Allow-Origin should be the exact origin "
            f"{settings.frontend_url!r}, not {acao!r}."
        )

    # Also check that Access-Control-Allow-Credentials is 'true'
    acac = r.headers.get("access-control-allow-credentials", "")
    if acac:
        assert acac.lower() == "true", (
            f"Access-Control-Allow-Credentials must be 'true'. Got: {acac!r}"
        )


# ======================================================================
# Test 4 -- Allowed methods include required HTTP verbs
# ======================================================================


async def test_preflight_allows_required_methods(client):
    """OPTIONS preflight from allowed origin must list GET, POST, PATCH,
    DELETE, OPTIONS in Access-Control-Allow-Methods.

    Per spec section 10.6: allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"].
    """
    r = await client.options(
        "/health",
        headers={
            "Origin": settings.frontend_url,
            "Access-Control-Request-Method": "POST",
        },
    )
    acam = r.headers.get("access-control-allow-methods", "")
    # Parse comma-separated methods, normalize to uppercase
    allowed_methods = {m.strip().upper() for m in acam.split(",") if m.strip()}
    # PUT added by #410: it was missing, so the browser preflight for the FAQ
    # save (PUT /branches/{id}/faq — the app's only PUT) returned 400 and the
    # save died client-side while every server-side test stayed green.
    required = {"GET", "POST", "PUT", "PATCH", "DELETE"}
    missing = required - allowed_methods
    assert not missing, (
        f"Access-Control-Allow-Methods missing required methods: {missing}. "
        f"Got: {acam!r}. Spec section 10.6 requires GET, POST, PUT, PATCH, DELETE, OPTIONS."
    )


async def test_preflight_for_faq_put_succeeds(client):
    """#410 regression: the EXACT preflight the browser sends before the FAQ
    save. With PUT missing from allow_methods this returned 400 'Disallowed
    CORS method' and branches.faq stayed NULL in prod forever."""
    r = await client.options(
        "/branches/00000000-0000-0000-0000-000000000000/faq",
        headers={
            "Origin": settings.frontend_url,
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert r.status_code == 200, (
        f"FAQ-save preflight rejected ({r.status_code}): {r.text!r} — "
        "PUT missing from CORSMiddleware allow_methods?"
    )
    acam = {m.strip().upper() for m in r.headers.get("access-control-allow-methods", "").split(",")}
    assert "PUT" in acam


# ======================================================================
# Test 5 -- Allowed headers include Authorization and Content-Type
# ======================================================================


async def test_preflight_allows_required_headers(client):
    """OPTIONS preflight from allowed origin must list Authorization and
    Content-Type in Access-Control-Allow-Headers.

    Without Authorization, the browser will strip the Bearer JWT from
    cross-origin requests -- breaking authentication entirely.
    """
    r = await client.options(
        "/health",
        headers={
            "Origin": settings.frontend_url,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization, Content-Type",
        },
    )
    acah = r.headers.get("access-control-allow-headers", "")
    # Parse comma-separated headers, normalize to lowercase
    allowed_headers = {h.strip().lower() for h in acah.split(",") if h.strip()}
    required = {"authorization", "content-type"}
    missing = required - allowed_headers
    assert not missing, (
        f"Access-Control-Allow-Headers missing required headers: {missing}. "
        f"Got: {acah!r}. Without 'authorization', browser strips JWT from "
        "cross-origin requests."
    )

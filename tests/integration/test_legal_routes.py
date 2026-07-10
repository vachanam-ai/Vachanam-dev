"""Integration tests for Phase 4.5 Task 12 — legal document routes.

Verifies that GET /privacy, GET /terms, and GET /dpa:
  - Return 200 with content-type text/html
  - Contain expected heading text rendered from the source markdown files
  - Require no authentication (no Authorization header needed)

Uses the same httpx ASGITransport pattern as tests/security/test_headers.py.
Depends on the `redis` fixture (conftest.py) because the app lifespan wires
fastapi-limiter which requires a Redis connection on startup.
"""
import httpx
import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def client(redis):  # noqa: F811  (redis fixture from conftest.py)
    """ASGI test client wired to the Vachanam FastAPI app.

    The `redis` fixture (conftest.py) pre-flushes and tears down the test DB
    key-space; it also ensures the rate-limiter's Redis dependency is satisfied
    during lifespan startup so the app does not crash at test-client creation.
    """
    from backend.main import app

    transport = httpx.ASGITransport(app=app, client=("testclient", 123))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as ac:
        yield ac


# ── Test 1: /privacy ─────────────────────────────────────────────────────────


async def test_privacy_returns_html(client):
    """GET /privacy must return 200, content-type text/html, and contain
    a rendered <h1> heading and the word 'Privacy' from the markdown source.
    """
    r = await client.get("/privacy")
    assert r.status_code == 200, (
        f"Expected 200 from GET /privacy, got {r.status_code}. "
        f"Body: {r.text[:200]}"
    )
    ct = r.headers.get("content-type", "")
    assert ct.startswith("text/html"), (
        f"Expected content-type text/html, got: {ct!r}"
    )
    assert "<h1" in r.text, (
        "Response body must contain a rendered <h1> heading from the markdown."
    )
    assert "Privacy" in r.text, (
        "Response body must contain the word 'Privacy' from the rendered heading."
    )


# ── Test 2: /terms ────────────────────────────────────────────────────────────


async def test_terms_returns_html(client):
    """GET /terms must return 200, content-type text/html, and contain
    the word 'Terms' from the rendered markdown.
    """
    r = await client.get("/terms")
    assert r.status_code == 200, (
        f"Expected 200 from GET /terms, got {r.status_code}. "
        f"Body: {r.text[:200]}"
    )
    ct = r.headers.get("content-type", "")
    assert ct.startswith("text/html"), (
        f"Expected content-type text/html for /terms, got: {ct!r}"
    )
    assert "Terms" in r.text, (
        "Response body must contain 'Terms' from the rendered markdown."
    )


# ── Test 3: /dpa ──────────────────────────────────────────────────────────────


async def test_dpa_returns_html(client):
    """GET /dpa must return 200, content-type text/html, and contain
    the words 'Data Processing' from the rendered markdown.
    """
    r = await client.get("/dpa")
    assert r.status_code == 200, (
        f"Expected 200 from GET /dpa, got {r.status_code}. "
        f"Body: {r.text[:200]}"
    )
    ct = r.headers.get("content-type", "")
    assert ct.startswith("text/html"), (
        f"Expected content-type text/html for /dpa, got: {ct!r}"
    )
    assert "Data Processing" in r.text, (
        "Response body must contain 'Data Processing' from the rendered markdown."
    )


# ── Test 4: public access — no auth header required ───────────────────────────


async def test_legal_no_auth_required(client):
    """All three legal routes must return 200 even without an Authorization header.

    Legal disclosures must be publicly accessible. Any auth enforcement
    on these routes is a bug.
    """
    for path in ("/privacy", "/terms", "/dpa"):
        r = await client.get(path)  # deliberately no Authorization header
        assert r.status_code == 200, (
            f"GET {path} without Authorization header must return 200, "
            f"got {r.status_code}. Legal pages must be publicly accessible."
        )


# ── Test 5: Cache-Control header on /privacy ────────────────────────────────


async def test_privacy_cache_control_header(client):
    """GET /privacy must include Cache-Control: public, max-age=3600.

    Legal documents are static and cache-friendly. The header reduces
    origin load and lets CDN / browser cache serve repeat requests.
    """
    r = await client.get("/privacy")
    assert r.status_code == 200
    cc = r.headers.get("cache-control", "")
    assert "public" in cc, (
        f"Expected 'public' in Cache-Control header, got: {cc!r}"
    )
    assert "max-age=3600" in cc, (
        f"Expected 'max-age=3600' in Cache-Control header, got: {cc!r}"
    )


# ── Test 6: Cache-Control header on /terms ───────────────────────────────────


async def test_terms_cache_control_header(client):
    """GET /terms must include Cache-Control: public, max-age=3600."""
    r = await client.get("/terms")
    assert r.status_code == 200
    cc = r.headers.get("cache-control", "")
    assert "public" in cc, (
        f"Expected 'public' in Cache-Control header for /terms, got: {cc!r}"
    )
    assert "max-age=3600" in cc, (
        f"Expected 'max-age=3600' in Cache-Control header for /terms, got: {cc!r}"
    )


# ── Test 7: Cache-Control header on /dpa ─────────────────────────────────────


async def test_dpa_cache_control_header(client):
    """GET /dpa must include Cache-Control: public, max-age=3600."""
    r = await client.get("/dpa")
    assert r.status_code == 200
    cc = r.headers.get("cache-control", "")
    assert "public" in cc, (
        f"Expected 'public' in Cache-Control header for /dpa, got: {cc!r}"
    )
    assert "max-age=3600" in cc, (
        f"Expected 'max-age=3600' in Cache-Control header for /dpa, got: {cc!r}"
    )


# ── Test 8: /privacy returns 503 when markdown file is missing ───────────────


async def test_privacy_returns_503_when_md_missing(redis, monkeypatch):
    """When the privacy policy markdown is absent at startup, GET /privacy
    must return 503 Service Unavailable.

    Simulates the file-missing case by monkeypatching the module-level
    cached HTML to None (as _load_doc returns None when the file is missing).
    Uses a fresh client to pick up the patched state.
    """
    import backend.routers.legal as legal_mod

    # Patch the cached HTML to None — simulates _load_doc returning None
    monkeypatch.setattr(legal_mod, "_PRIVACY_HTML", None)

    transport = httpx.ASGITransport(app=legal_mod.router.app, client=("testclient", 123))

    # Re-import the full app to get a client that uses the patched module
    from backend.main import app

    transport = httpx.ASGITransport(app=app, client=("testclient", 123))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as ac:
        r = await ac.get("/privacy")
        assert r.status_code == 503, (
            f"Expected 503 when privacy markdown is missing, got {r.status_code}. "
            f"Body: {r.text[:200]}"
        )


# ── /data-handling (FIXLOG #301: DPDP transparency doc) ──────────────────────


async def test_data_handling_returns_html(client):
    """GET /data-handling must return 200 HTML with the rendered doc — the
    DPDP transparency page has to be publicly reachable, like /privacy."""
    r = await client.get("/data-handling")
    assert r.status_code == 200, (
        f"Expected 200 from GET /data-handling, got {r.status_code}. "
        f"Body: {r.text[:200]}"
    )
    assert r.headers.get("content-type", "").startswith("text/html")
    assert "<h1" in r.text
    assert "Handles Your Data" in r.text


async def test_privacy_policy_matches_reality():
    """The policy must describe what the code DOES: transcripts ARE stored
    (masked, 90 days) — the old 'NOT STORED' wording was false; and the STT
    processor table must name Soniox (primary) + Sarvam (fallback)."""
    from pathlib import Path

    text = Path("docs/legal/privacy-policy.md").read_text(encoding="utf-8")
    assert "Soniox" in text
    assert "Sarvam" in text  # still listed — it is the live fallback
    assert "90 days" in text  # transcript retention disclosed
    assert "| Voice call transcripts | NOT STORED |" not in text

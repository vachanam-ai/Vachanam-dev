"""RED tests for Phase 4.5 Task 5 — fastapi-limiter rate limiting.

These tests are the SPEC for the implementer (backend-engineer, Task 5).
They are committed RED — backend-engineer makes them GREEN by wiring
fastapi-limiter into backend/main.py + per-route Depends() decorators
per spec §6 (`docs/superpowers/specs/2026-05-22-security-hardening-design.md`).

Per tester.md rule 1: failing test FIRST is the deliverable.
Per tester.md rule 7: every endpoint has negative tests (429 is one).
Per tester.md rule 9: real Redis (Docker) — uses the `redis` fixture.
Per tester.md rule 5: no hardcoded URLs, phones, or secrets — use Faker/settings/fixtures.

────────────────────────────────────────────────────────────────────────
Spec §6 — what the implementer (Task 5) must build to turn these GREEN:

1. Add `fastapi-limiter` to backend/requirements.txt
2. In backend/main.py lifespan: `await FastAPILimiter.init(redis_url, identifier=user_or_ip_key)`
3. Implement `backend/middleware/rate_limit.py` with:
   - `async def user_or_ip_key(request: Request) -> str` per spec §6.2
   - exports for per-route RateLimiter dependencies sized per §6.3 table
4. Decorate each endpoint in spec §6.3 with `dependencies=[Depends(RateLimiter(times=N, seconds=60))]`
5. On 429: include `Retry-After: <seconds>` header (fastapi-limiter does this natively)
6. Bypass: read `settings.rate_limit_bypass_ips` (comma-separated env var); if
   `request.client.host in bypass_set`, return a constant key that's never
   incremented, OR short-circuit the dependency. Implementer's choice.
7. Failed-Google-ID-verification IP block (spec §5.6):
   - On 5 failures from same IP within 10 min → `SADD blocked_ips <ip>` with EXPIRE 3600
   - Auth dependency checks `SISMEMBER blocked_ips <ip>` → 403 if blocked
   - Counter Redis key: `auth_fail:<ip>` with EXPIRE 600 (10 min sliding)

If the implementer changes any of these test files to make them pass
(weakening an assertion, lowering N, marking skip), security-engineer
review (Task 5 reviewer) MUST reject and re-dispatch.
────────────────────────────────────────────────────────────────────────
"""
import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
from jose import jwt

from backend.config import settings


# ──────────────────────────────────────────────────────────────────────
# Test infrastructure
# ──────────────────────────────────────────────────────────────────────

# httpx.AsyncClient against the in-process ASGI app gives us a deterministic
# request.client.host. IMPORTANT: httpx.ASGITransport defaults to ("127.0.0.1", 123),
# NOT "testclient" (that was the old Starlette sync TestClient convention). We
# explicitly set client=("testclient", 123) on the transport so all assertions
# in this file that reference "testclient" as the IP string are correct.
# Implementer note: rate-limit key for unauthenticated requests must NOT crash
# when request.client is None or its .host is "testclient" — handle both.


def _make_jwt(
    user_id: str | None = None,
    email: str = "ratelimit-test@vachanam.in",
    role: str = "receptionist",
    org_id: str | None = None,
    branch_ids: list[str] | None = None,
    is_admin: bool = False,
    expired: bool = False,
) -> str:
    """Mint a Vachanam-signed JWT for rate-limit identity tests.

    Does NOT touch the DB — the rate limiter's user_or_ip_key (spec §6.2) decodes
    with verify_exp=False, so it only needs a valid signature + a `sub` claim.
    """
    now = datetime.now(timezone.utc)
    exp = now - timedelta(hours=1) if expired else now + timedelta(hours=settings.jwt_expire_hours)
    payload = {
        "sub": user_id or str(uuid.uuid4()),
        "email": email,
        "role": role,
        "org_id": org_id or str(uuid.uuid4()),
        "branch_ids": branch_ids or [str(uuid.uuid4())],
        "is_admin": is_admin,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


@pytest_asyncio.fixture
async def client(redis):
    """ASGI httpx client against backend.main.app.

    Depends on the `redis` fixture so each test starts with a flushed Redis
    (the rate-limit counters live there). Per tester.md rule 9 we use the
    real Redis from docker-compose (no fakeredis).
    """
    # Import inside the fixture so app construction sees the latest settings/env
    from backend.main import app

    # client=("testclient", 123) makes request.client.host == "testclient".
    # httpx ASGITransport default is ("127.0.0.1", 123), NOT "testclient".
    transport = httpx.ASGITransport(app=app, client=("testclient", 123))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


# ──────────────────────────────────────────────────────────────────────
# Group 1 — /auth/google: 5/min per IP, 6th request → 429 + Retry-After
# Spec §6.3 row 1
# ──────────────────────────────────────────────────────────────────────


async def test_sixth_auth_google_within_60s_returns_429(client, redis):
    """6th call to /auth/google in 60s from one IP → 429 (spec §6.3).

    First 5 are allowed (they fail auth with 401 because the id_token is junk —
    that's fine, the LIMITER counts ATTEMPTS not successes). The 6th must be
    rejected by the limiter before reaching the handler.

    Note: junk id_token will return 401 from auth handler (Google verification
    fails). The point is the limiter counts these against the IP. If you see
    500s, your impl is crashing — fix that first. If you see all 5 as 401 and
    the 6th as 401 too, the limiter is NOT wired. If the 6th is 429, GREEN.
    """
    body = {"id_token": "junk.invalid.token"}
    statuses = []
    for _ in range(6):
        r = await client.post("/auth/google", json=body)
        statuses.append(r.status_code)

    # First five should NOT be rate-limited (they'll be 401 or similar from auth)
    assert all(s != 429 for s in statuses[:5]), (
        f"Requests 1-5 must not be 429 (got {statuses[:5]}). "
        "Either limiter is set too tight (<5/min) or app is crashing (500s)."
    )
    # The sixth MUST be 429
    assert statuses[5] == 429, (
        f"6th /auth/google request must be 429 per spec §6.3 (got {statuses[5]}). "
        "Limiter is not wired or the per-route limit is wrong."
    )


async def test_429_response_includes_retry_after_header(client, redis):
    """When 429 returned, Retry-After header must be present (spec §6.4)."""
    body = {"id_token": "junk.invalid.token"}
    # Burn through the 5/min budget
    last_response = None
    for _ in range(6):
        last_response = await client.post("/auth/google", json=body)

    assert last_response.status_code == 429, (
        f"Expected 429 after 6 hits, got {last_response.status_code}. "
        "Retry-After assertion cannot run until 429 is returned."
    )
    # fastapi-limiter sets Retry-After natively. Header name is case-insensitive
    # but httpx normalizes; check both common casings.
    assert "retry-after" in {h.lower() for h in last_response.headers.keys()}, (
        f"429 response missing Retry-After header. Headers present: {list(last_response.headers.keys())}"
    )
    retry_after_value = last_response.headers.get("Retry-After") or last_response.headers.get("retry-after")
    # Must be a non-negative integer (seconds to wait)
    try:
        wait_s = int(retry_after_value)
    except (TypeError, ValueError):
        pytest.fail(f"Retry-After must be an integer number of seconds, got: {retry_after_value!r}")
    assert 0 <= wait_s <= 60, f"Retry-After {wait_s}s out of expected 0-60s window for a /min limiter"


# ──────────────────────────────────────────────────────────────────────
# Group 2 — IP blocklist after 5 failed Google verifications (spec §5.6)
# This is INDEPENDENT of the 429 rate limit. The 429 is throttling; this is
# a 1-hour 403 block stored in Redis.
# ──────────────────────────────────────────────────────────────────────


async def test_five_failed_google_verifications_blocks_ip_in_redis(client, redis, monkeypatch):
    """5 failed Google ID-token verifications from same IP → IP entered into
    Redis blocklist for 1h (spec §5.6).

    Implementer note: counter key shape suggested = `auth_fail:<ip>`,
    block set key shape = `blocked_ips` (SET) with member = IP.
    Implementer may choose alternative shapes, but blocking behavior is
    the contract.
    """
    # Set a fake GOOGLE_OAUTH_CLIENT_ID so the handler proceeds past the
    # "OAuth not configured" early-return (which correctly does NOT count
    # against the IP blocklist) and reaches google_id_token.verify_oauth2_token()
    # which raises ValueError for junk tokens -> triggers record_failed_login().
    monkeypatch.setattr(settings, "google_oauth_client_id", "fake-client-id-for-test.apps.googleusercontent.com")

    body = {"id_token": "junk.invalid.token"}
    # 5 failed attempts (each 401 from google verify). Limiter is 5/min so the
    # 5th still goes through to the handler; the 6th would be 429 (Group 1).
    for _ in range(5):
        r = await client.post("/auth/google", json=body)
        # We don't care about the exact status here — we care that
        # afterwards the IP is in Redis blocklist.
        assert r.status_code != 500, f"App crashed on /auth/google: {r.text}"

    # After 5 failures, the IP must be on the blocklist
    # Implementer may store as SET member or as a single key — accept either.
    is_blocked_set_member = await redis.sismember("blocked_ips", "testclient")
    is_blocked_key_exists = await redis.exists("blocked_ips:testclient")
    assert is_blocked_set_member or is_blocked_key_exists, (
        "After 5 failed Google ID verifications from the same IP, the IP must "
        "be in Redis under either `blocked_ips` SET or `blocked_ips:<ip>` key "
        "(spec §5.6). Found neither."
    )


async def test_blocked_ip_returns_403_on_next_auth_attempt(client, redis):
    """Once IP is in blocked_ips, subsequent /auth/google → 403 (not 401, not 429).

    Critical distinction: 403 means "we know who you are and you're banned",
    not "rate-limited, try later" (429) or "credentials bad" (401).
    """
    # Pre-seed the blocklist as if 5 failures already happened. Use BOTH shapes
    # since the implementer is free to pick one — we want the test to pass
    # regardless of which storage strategy they chose.
    await redis.sadd("blocked_ips", "testclient")
    await redis.set("blocked_ips:testclient", "1", ex=3600)

    body = {"id_token": "junk.invalid.token"}
    r = await client.post("/auth/google", json=body)
    assert r.status_code == 403, (
        f"Blocked IP must get 403, got {r.status_code}. "
        "Auth handler / rate-limit middleware must check blocked_ips before "
        "doing Google verification."
    )


# ──────────────────────────────────────────────────────────────────────
# Group 3 — Trusted IP bypass via RATE_LIMIT_BYPASS_IPS env (spec §6.5)
# ──────────────────────────────────────────────────────────────────────


def test_settings_exposes_rate_limit_bypass_ips_field():
    """Spec §6.5 — RATE_LIMIT_BYPASS_IPS env var must be a typed field on
    backend.config.Settings so the rate-limit middleware can read it.

    Without this field, the bypass cannot be configured per spec. This is a
    structural assertion separate from runtime behavior (next test).
    """
    from backend.config import settings as s
    assert hasattr(s, "rate_limit_bypass_ips"), (
        "backend.config.Settings missing `rate_limit_bypass_ips` field. "
        "Spec §6.5 requires RATE_LIMIT_BYPASS_IPS env var → settings field "
        "so the limiter can opt-out trusted IPs (Vinay's office, monitoring, etc.)."
    )


async def test_trusted_ip_bypasses_rate_limit(client, redis, monkeypatch):
    """IP in RATE_LIMIT_BYPASS_IPS env var bypasses the limiter entirely.

    Spec §6.5. Implementer must read `settings.rate_limit_bypass_ips` (CSV
    string OR list — implementer's call, but document the shape). When the
    request's client.host is in that set, the limiter does not count or
    reject the request.

    Test method:
      Phase A: WITHOUT bypass set, 6 hits → 6th must be 429 (proves limiter exists)
      Phase B: WITH bypass=testclient, 20 hits → zero 429s

    If Phase A doesn't fire 429, the limiter isn't wired and this test
    can't meaningfully assert anything — flagged as failure either way.
    """
    # ── Phase A — confirm limiter is active when bypass is unset ─────────
    monkeypatch.delenv("RATE_LIMIT_BYPASS_IPS", raising=False)
    from importlib import reload
    from backend import config as cfg_mod
    reload(cfg_mod)
    from backend import main as main_mod_a
    reload(main_mod_a)

    transport_a = httpx.ASGITransport(app=main_mod_a.app)
    async with httpx.AsyncClient(transport=transport_a, base_url="http://testserver") as ac:
        phase_a_statuses = []
        for _ in range(6):
            r = await ac.post("/auth/google", json={"id_token": "junk.invalid"})
            phase_a_statuses.append(r.status_code)

    assert phase_a_statuses[5] == 429, (
        f"Phase A precondition: with bypass UNSET, 6th /auth/google must be 429 "
        f"(got {phase_a_statuses[5]}). Limiter is not wired — bypass test is "
        f"meaningless until limiter exists. Statuses: {phase_a_statuses}"
    )

    # ── Phase B — with bypass set, 20 hits must yield zero 429s ──────────
    monkeypatch.setenv("RATE_LIMIT_BYPASS_IPS", "testclient,127.0.0.1")
    reload(cfg_mod)
    from backend import main as main_mod_b
    reload(main_mod_b)

    transport_b = httpx.ASGITransport(app=main_mod_b.app)
    async with httpx.AsyncClient(transport=transport_b, base_url="http://testserver") as ac:
        phase_b_statuses = []
        for _ in range(20):
            r = await ac.post("/auth/google", json={"id_token": "junk.invalid"})
            phase_b_statuses.append(r.status_code)

    assert 429 not in phase_b_statuses, (
        f"Phase B: trusted IP in RATE_LIMIT_BYPASS_IPS got 429 — bypass not working. "
        f"Got statuses: {phase_b_statuses}."
    )


# ──────────────────────────────────────────────────────────────────────
# Group 4 — Per-user (JWT sub) keying vs per-IP (no JWT)
# Spec §6.2 — when Authorization Bearer is present, key by user_id
# ──────────────────────────────────────────────────────────────────────


async def test_user_a_exhausting_quota_does_not_affect_user_b(client, redis):
    """User A burns through /queue/{branch}/today limit → 429 for user A.
    User B (different JWT sub) from same IP still has fresh quota.

    Spec §6.2 + §6.3 — /queue/{branch}/today is 60/min per user.
    The two users share an IP but their counters are independent because the
    key_func returns `user:<sub>` when JWT is present.
    """
    user_a_id = str(uuid.uuid4())
    user_b_id = str(uuid.uuid4())
    shared_branch = str(uuid.uuid4())
    jwt_a = _make_jwt(user_id=user_a_id, branch_ids=[shared_branch])
    jwt_b = _make_jwt(user_id=user_b_id, branch_ids=[shared_branch])

    # User A: hit the queue endpoint 61 times (limit is 60/min per user)
    # Note: each request will likely return 4xx because the branch doesn't exist
    # in the DB for this test. The point is the LIMITER counts the 61st.
    a_statuses = []
    for _ in range(61):
        r = await client.get(
            f"/queue/{shared_branch}/today",
            headers={"Authorization": f"Bearer {jwt_a}"},
        )
        a_statuses.append(r.status_code)

    assert a_statuses[60] == 429, (
        f"User A's 61st request must be 429 (got {a_statuses[60]}). "
        f"Per-user /queue rate limit is not 60/min or not user-keyed. "
        f"First 5 statuses: {a_statuses[:5]}, last 5: {a_statuses[-5:]}"
    )

    # User B: single request from SAME IP — must NOT be 429
    r_b = await client.get(
        f"/queue/{shared_branch}/today",
        headers={"Authorization": f"Bearer {jwt_b}"},
    )
    assert r_b.status_code != 429, (
        f"User B got 429 from same IP after User A exhausted quota — "
        f"limiter is IP-keyed instead of user-keyed for authenticated requests. "
        f"Got status {r_b.status_code}. Spec §6.2 requires user-keying."
    )


# ──────────────────────────────────────────────────────────────────────
# Group 5 — Cross-user isolation under concurrency
# 10 distinct users hitting same endpoint in parallel — each must get OWN quota
# Spec §6.2 — counters keyed by user_id, never shared across users
# ──────────────────────────────────────────────────────────────────────


async def test_ten_distinct_users_each_get_independent_quota(client, redis):
    """10 distinct user JWTs hit /queue/{branch}/today in parallel.

    Each must succeed (no user crosses its own per-user limit). We deliberately
    do NOT use N=100 here because the point of this test is per-user KEY
    ISOLATION across DIFFERENT user_ids, not concurrent hits on the SAME key
    (that's covered by tests/edge_cases/test_concurrent_tokens.py at N=100).

    If a single user's quota leaks to another's counter, some users will see
    429 spuriously.
    """
    branch = str(uuid.uuid4())
    jwts = [_make_jwt(user_id=str(uuid.uuid4()), branch_ids=[branch]) for _ in range(10)]

    async def hit_once(token: str) -> int:
        r = await client.get(
            f"/queue/{branch}/today",
            headers={"Authorization": f"Bearer {token}"},
        )
        return r.status_code

    statuses = await asyncio.gather(*[hit_once(t) for t in jwts])
    # Each user makes exactly 1 request — none should hit any limit
    assert all(s != 429 for s in statuses), (
        f"At least one of 10 distinct users got 429 on their FIRST request. "
        f"Quota is bleeding across user keys. Statuses: {statuses}"
    )


# ──────────────────────────────────────────────────────────────────────
# Group 6 — Per-endpoint limits per spec §6.3 table
# These assert the limiter is wired on each protected route at the right rate.
# We DO NOT actually hammer 1000 hits on /webhook/* — too slow, and webhook
# signature mocking is out of scope. Instead, we assert config is present
# by importing the rate-limit module and looking at exported dependencies.
# ──────────────────────────────────────────────────────────────────────


def test_rate_limit_module_exists_with_per_endpoint_limits():
    """Implementer must create backend/middleware/rate_limit.py exposing
    named RateLimiter dependencies sized per spec §6.3.

    Naming convention (implementer must honor — tests below assert presence):
        auth_google_limit      — 5/min per IP
        create_order_limit     — 10/min per user
        verify_payment_limit   — 30/min per user
        whatsapp_webhook_limit — 1000/min per IP
        razorpay_webhook_limit — 100/min per IP
        queue_today_limit      — 60/min per user
        admin_limit            — 30/min per user
        default_limit          — 100/min per user/IP
    """
    try:
        from backend.middleware import rate_limit as rl
    except ImportError:
        pytest.fail(
            "backend/middleware/rate_limit.py does not exist. "
            "Task 5 implementer must create it per spec §6.2 / §6.3."
        )

    required_names = [
        "auth_google_limit",
        "create_order_limit",
        "verify_payment_limit",
        "whatsapp_webhook_limit",
        "razorpay_webhook_limit",
        "queue_today_limit",
        "admin_limit",
        "default_limit",
    ]
    missing = [n for n in required_names if not hasattr(rl, n)]
    assert not missing, (
        f"backend/middleware/rate_limit.py missing required limiter dependencies: {missing}. "
        f"Each must be a fastapi-limiter RateLimiter() instance sized per spec §6.3."
    )


def test_user_or_ip_key_function_exists():
    """Implementer must export `user_or_ip_key` async function per spec §6.2."""
    try:
        from backend.middleware import rate_limit as rl
    except ImportError:
        pytest.fail("backend/middleware/rate_limit.py does not exist (see prior test).")
    assert hasattr(rl, "user_or_ip_key"), (
        "backend/middleware/rate_limit.py must export `async def user_or_ip_key(request)` "
        "per spec §6.2 — returns 'user:<sub>' if JWT present else 'ip:<host>'."
    )
    assert asyncio.iscoroutinefunction(rl.user_or_ip_key), (
        "user_or_ip_key must be `async def` (fastapi-limiter identifier contract)."
    )


async def test_user_or_ip_key_returns_user_key_for_valid_jwt():
    """Direct unit-style check of the key function with a valid JWT."""
    from unittest.mock import MagicMock
    try:
        from backend.middleware.rate_limit import user_or_ip_key
    except ImportError:
        pytest.fail("backend/middleware/rate_limit.user_or_ip_key not implemented (Task 5).")

    sub = str(uuid.uuid4())
    token = _make_jwt(user_id=sub)
    req = MagicMock()
    req.headers = {"authorization": f"Bearer {token}"}
    req.client.host = "1.2.3.4"

    key = await user_or_ip_key(req)
    assert key == f"user:{sub}", (
        f"With valid JWT, key must be 'user:<sub>', got {key!r}. Spec §6.2."
    )


async def test_user_or_ip_key_returns_ip_key_when_no_jwt():
    """Without Authorization header, key must be 'ip:<client.host>'."""
    from unittest.mock import MagicMock
    try:
        from backend.middleware.rate_limit import user_or_ip_key
    except ImportError:
        pytest.fail("backend/middleware/rate_limit.user_or_ip_key not implemented (Task 5).")

    req = MagicMock()
    req.headers = {}
    req.client.host = "10.0.0.1"

    key = await user_or_ip_key(req)
    assert key == "ip:10.0.0.1", (
        f"Without JWT, key must be 'ip:<host>', got {key!r}. Spec §6.2."
    )


async def test_user_or_ip_key_falls_back_to_ip_on_bad_jwt():
    """Malformed Bearer token must NOT crash key_func — falls back to IP keying.

    Spec §6.2 example wraps jwt.decode in try/except and falls back to IP.
    """
    from unittest.mock import MagicMock
    try:
        from backend.middleware.rate_limit import user_or_ip_key
    except ImportError:
        pytest.fail("backend/middleware/rate_limit.user_or_ip_key not implemented (Task 5).")

    req = MagicMock()
    req.headers = {"authorization": "Bearer garbage.not.a.jwt"}
    req.client.host = "10.0.0.2"

    key = await user_or_ip_key(req)
    assert key == "ip:10.0.0.2", (
        f"Malformed JWT must fall back to IP keying, got {key!r}. "
        "Spec §6.2 wraps decode in try/except for this reason."
    )

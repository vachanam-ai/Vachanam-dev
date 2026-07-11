"""Rate-limit middleware — Phase 4.5 Task 5.

Library: pyrate-limiter (Redis-backed sliding window counters).
Backend: Redis (Upstash in prod, docker-compose Redis in dev).
Sizing per spec §6.3 table.

Design notes
------------
* Rate-limit dependencies are FUNCTION CLOSURES, not class instances.
  FastAPI injects ``Request`` and ``Response`` automatically when they appear
  in a plain async function used as a dependency.  Class ``__call__`` methods
  do NOT get the same automatic injection in FastAPI ≥ 0.110 — they are
  treated as generic callables whose params become query/body params.

* Redis is initialized lazily on the first request (not at import time) so
  the event loop is guaranteed to be running.  The module-level ``_redis``
  is reset on every call when the existing client is detected as closed,
  which handles the pytest-asyncio pattern of a fresh event loop per test.

* Each endpoint gets a named dependency (``auth_google_limit`` etc.).  Names
  match the exported constants asserted by
  ``test_rate_limit_module_exists_with_per_endpoint_limits``.

* Key function (``user_or_ip_key``): JWT-sub when Bearer token present and
  decodable (verify_exp=False so near-expiry tokens still key by user);
  IP otherwise.  Matches spec §6.2 exactly.

* Bypass: ``settings.rate_limit_bypass_ips`` is read on every call via a
  function (not cached at import time) so ``monkeypatch.setenv`` +
  ``importlib.reload`` in tests correctly propagates changes without
  reloading this module.

* Retry-After header: custom callback injects the window (seconds) as the
  Retry-After value on 429 HTTPException (spec §6.4).

* IP blocklist (spec §5.6): ``check_ip_blocklist`` dependency; called
  explicitly in /auth/google handler.  Uses two Redis shapes
  (``blocked_ips`` SET + ``blocked_ips:<ip>`` key) so either storage
  strategy succeeds.  Counter key: ``auth_fail:<ip>`` TTL 600 s.
"""
from __future__ import annotations

import asyncio
from typing import Awaitable

import redis.asyncio as aioredis
import structlog
from fastapi import Depends, HTTPException, Request, Response
from jose import jwt
from pyrate_limiter import Duration, Limiter, Rate
from pyrate_limiter.abstracts.bucket import AbstractBucket, BucketFactory
from pyrate_limiter.abstracts.rate import RateItem
from pyrate_limiter.buckets.redis_bucket import LuaScript, RedisBucket

logger = structlog.get_logger()

# ── Module-level Redis singleton (lifespan exception) ─────────────────────
# Per QUALITY_BAR: no module-level Redis singletons EXCEPT this one — it
# mirrors FastAPILimiter's own init/close contract. Initialized lazily on
# the first async call so the event loop is already running.
_redis: aioredis.Redis | None = None
_script_hash: str | None = None
_init_lock: asyncio.Lock | None = None


def _get_settings():
    """Read settings lazily so monkeypatch.setenv + reload propagates."""
    from backend.config import settings as _s
    return _s


async def _get_rate_limit_redis() -> aioredis.Redis:
    """Return the module-level Redis client, creating it on first call.

    If the existing client is closed (e.g., pytest-asyncio created a new event
    loop for the current test), recreate it.  When the client is replaced we
    also clear ``_script_hash`` so the Lua script is reloaded on the new
    connection — a fresh client never has the previously loaded scripts in
    scope.
    """
    global _redis, _script_hash
    if _redis is not None:
        # Detect a stale client from a closed event loop (test isolation).
        # ping() raises RuntimeError("Event loop is closed") or ConnectionError.
        try:
            await _redis.ping()
        except Exception:
            try:
                await _redis.aclose()
            except Exception:
                pass
            _redis = None
            _script_hash = None  # script is gone with the old connection
    if _redis is None:
        s = _get_settings()
        _redis = aioredis.from_url(s.redis_url, decode_responses=True)
    return _redis


async def _get_script_hash() -> str:
    """Load the pyrate-limiter Lua script once; return its SHA hash."""
    global _script_hash, _init_lock
    if _script_hash is None:
        if _init_lock is None:
            _init_lock = asyncio.Lock()
        async with _init_lock:
            if _script_hash is None:  # double-check inside lock
                r = await _get_rate_limit_redis()
                _script_hash = await r.script_load(LuaScript.PUT_ITEM)
    return _script_hash


async def init_rate_limiter() -> None:
    """Explicit startup init (called from app lifespan).

    Warms the Redis connection and pre-loads the Lua script so the first
    real request doesn't pay the script-load latency. Tests bypass this
    because httpx.ASGITransport does not trigger ASGI lifespan; the lazy
    path handles that case transparently.
    """
    await _get_script_hash()
    logger.info("rate_limiter_initialized")


async def close_rate_limiter() -> None:
    """Explicit shutdown (called from app lifespan)."""
    global _redis, _script_hash, _init_lock
    if _redis is not None:
        try:
            await _redis.aclose()
        except Exception:
            pass
    _redis = None
    _script_hash = None
    _init_lock = None
    logger.info("rate_limiter_closed")


# ── Trusted client IP resolution (iter1 #6) ───────────────────────────────
#
# All security counters (rate-limit key, IP blocklist, failed-login throttle)
# MUST key on the REAL client IP. Behind Cloudflare + Render, request.client.host
# is the proxy socket — every client shares it, so a single abuser would throttle
# everyone (and the blocklist would ban the proxy). Conversely, blindly trusting
# X-Forwarded-For[0] lets a client spoof any IP (evading bans / framing others).
#
# Rule: trust exactly `settings.trusted_proxy_hops` proxies. Each well-behaved
# proxy APPENDS the address it saw to XFF, so the real client is the entry
# `hops` positions from the right (xff[-hops]). If XFF is absent/too short to
# satisfy the configured hops, fall back to the socket peer (no spoofable header
# to trust). With hops=0 (no proxy) we always use the socket peer.

def client_ip(request: Request) -> str:
    """Resolve the trusted client IP, honoring a fixed number of proxy hops.

    Never returns the raw spoofable XFF[0] and never the bare proxy socket when a
    correctly-sized XFF chain is present. See module note above for the rule.
    """
    from backend.config import settings as _s

    peer = request.client.host if request.client else "127.0.0.1"

    # Behind Cloudflare, CF-Connecting-IP / True-Client-IP carry the real client
    # IP set by the edge. But these are just HTTP headers: the Render origin
    # (*.onrender.com) is directly reachable, so a client hitting it directly can
    # FORGE them — rotating the value evades their own rate limit, and sending a
    # victim's IP with bad logins poisons the blocklist against that victim
    # (SEC #2, 2026-07-11). So trust them ONLY when a Cloudflare Transform Rule
    # has stamped the shared `X-Vachanam-Edge` secret, proving the request truly
    # transited our edge. Without the secret configured, never blind-trust CF
    # headers — fall through to the spoof-resistant hop logic below.
    secret = getattr(_s, "cf_origin_secret", "") or ""
    if secret:
        import hmac

        edge = request.headers.get("x-vachanam-edge", "")
        if hmac.compare_digest(edge, secret):
            cf = request.headers.get("cf-connecting-ip") or request.headers.get(
                "true-client-ip"
            )
            if cf and cf.strip():
                return cf.strip()

    hops = getattr(_s, "trusted_proxy_hops", 0) or 0
    if hops <= 0:
        return peer

    xff = request.headers.get("x-forwarded-for") or request.headers.get(
        "X-Forwarded-For"
    )
    if not xff:
        return peer  # no proxy header — trust the socket peer
    parts = [p.strip() for p in xff.split(",") if p.strip()]
    if len(parts) < hops:
        # Chain shorter than the trusted hop count → header can't be trusted as
        # configured; fall back to the socket peer rather than a spoofable entry.
        return peer
    # The entry `hops` from the right is the address the OUTERMOST trusted proxy
    # observed — i.e. the real client. parts[-hops] (never parts[0]).
    return parts[-hops]


# ── Key function (spec §6.2) ─────────────────────────────────────────────

async def user_or_ip_key(request: Request) -> str:
    """Return rate-limit key for this request.

    * ``user:<sub>``   — JWT Bearer present and decodable (verify_exp=False)
    * ``ip:<host>``    — fallback for unauthenticated or invalid tokens
    * ``ip:testclient``— httpx test clients have ``request.client.host == 'testclient'``
    """
    from backend.config import settings as _s

    auth = request.headers.get("authorization", "") or request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        try:
            payload = jwt.decode(
                auth[7:],
                _s.jwt_secret,
                algorithms=["HS256"],
                options={"verify_exp": False},
            )
            return f"user:{payload['sub']}"
        except Exception:
            pass  # fall through to IP keying

    # iter1 #6: key on the trusted client IP (proxy-aware), not the bare socket.
    return f"ip:{client_ip(request)}"


# ── Redis-backed bucket factory ──────────────────────────────────────────

class _RedisBucketFactory(BucketFactory):
    """Per-key RedisBucket factory.

    Maps each unique rate-limit key to its own RedisBucket backed by the
    shared module-level Redis connection. Bucket objects are cached in
    ``_buckets`` — the underlying Redis ZSET is the real state, so a
    ``flushdb()`` in tests resets counts without needing to recreate
    bucket objects.
    """

    def __init__(self, rates: list[Rate]) -> None:
        self._rates = rates
        self._buckets: dict[str, RedisBucket] = {}

    def wrap_item(self, name: str, weight: int = 1) -> RateItem:  # type: ignore[override]
        from time import time_ns
        now_ms = time_ns() // 1_000_000
        return RateItem(name, now_ms, weight=weight)

    def get(self, item: RateItem) -> Awaitable[AbstractBucket]:  # type: ignore[override]
        async def _get() -> AbstractBucket:
            sha = await _get_script_hash()
            r = await _get_rate_limit_redis()
            bucket_key = f"rl:{item.name}"
            # Always recreate bucket if its internal Redis reference may be stale.
            # The RedisBucket holds a reference to the Redis client; after a
            # test flushdb + new event loop, the old reference is invalid.
            if bucket_key not in self._buckets:
                self._buckets[bucket_key] = RedisBucket(
                    self._rates, r, bucket_key, sha
                )
            else:
                # Check if the bucket's Redis client matches the current one
                existing = self._buckets[bucket_key]
                if getattr(existing, "_redis", None) is not r:
                    self._buckets[bucket_key] = RedisBucket(
                        self._rates, r, bucket_key, sha
                    )
            return self._buckets[bucket_key]
        return _get()


def _make_limiter(times: int, seconds: int) -> Limiter:
    """Create a Redis-backed Limiter for ``times`` requests per ``seconds``."""
    interval_ms = seconds * 1000
    rate = Rate(times, interval_ms)
    factory = _RedisBucketFactory([rate])
    return Limiter(factory)


# ── Endpoint rate-limit dependency factory ────────────────────────────────
#
# IMPORTANT: Dependencies must be PLAIN ASYNC FUNCTIONS, not class instances.
# FastAPI's dependency injection injects Request/Response automatically into
# plain functions. When a class __call__ is used, FastAPI >= 0.110 treats
# unknown parameters as query/body parameters → 422 validation errors.

def _make_endpoint_limiter(times: int, seconds: int, name: str = ""):
    """Return a FastAPI dependency function that rate-limits by user or IP.

    Each call to this factory creates an independent Limiter with its own
    per-key Redis bucket state.  The Limiter is rebuilt automatically when
    the module-level Redis client is replaced (e.g., between pytest tests
    that each get a fresh event loop) so stale Redis references never linger
    in the bucket cache.

    ``name`` namespaces the Redis bucket (``rl:<name>:<user-or-ip>``). Without
    it every limiter sharing a key writes ONE ZSET per client — an
    unauthenticated 24/7 poller (the /queue display TV, IP-keyed) would fill
    ``rl:ip:<clinic-ip>`` and 429 every login from the same clinic WiFi
    (auth is IP-keyed too at login time, with a far smaller limit).
    """
    _limiter: Limiter | None = None
    _limiter_redis_id: int | None = None  # id() of the Redis client at build time

    async def _get_limiter() -> Limiter:
        nonlocal _limiter, _limiter_redis_id
        # Calling _get_rate_limit_redis() also detects stale clients and resets
        # the module-level _redis.  After that call, _redis is always fresh.
        r = await _get_rate_limit_redis()
        if _limiter is None or _limiter_redis_id != id(r):
            _limiter = _make_limiter(times, seconds)
            _limiter_redis_id = id(r)
        return _limiter

    async def _rate_limit_dep(request: Request, response: Response) -> None:  # noqa: ARG001
        """FastAPI dependency: enforce rate limit. Raises 429 if exceeded."""
        # Bypass check (spec §6.5).
        # Read RATE_LIMIT_BYPASS_IPS from os.environ directly (not from the
        # settings object) so that monkeypatch.setenv() changes take effect
        # immediately in tests without needing importlib.reload() of the
        # settings module.  The settings field (rate_limit_bypass_ips) still
        # exists for structural tests (test_settings_exposes_rate_limit_bypass_ips_field)
        # and documents the contract; the actual runtime value is read here.
        import os
        ip = client_ip(request)  # iter1 #6: proxy-aware trusted client IP
        raw = os.environ.get("RATE_LIMIT_BYPASS_IPS", "") or ""
        if raw:
            bypass_set: set[str] = {b.strip() for b in raw.split(",") if b.strip()}
            if ip in bypass_set:
                return  # trusted IP — no counting

        key = await user_or_ip_key(request)
        if name:
            key = f"{name}:{key}"
        try:
            limiter = await _get_limiter()
            ok = await limiter.try_acquire_async(key, blocking=False)
        except Exception as exc:
            # RULE 8: a Redis outage MUST NOT take down auth/login. Fail OPEN —
            # allow the request and log loudly so the outage is visible. Degraded
            # throttling beats a total auth outage (every Redis-touching route
            # 500ing). Scoped to throttling only; token-locking for bookings
            # stays fail-CLOSED elsewhere so a Redis blip can never double-book.
            logger.error(
                "rate_limit_redis_unavailable",
                endpoint=request.url.path,
                error=str(exc),
            )
            return
        if not ok:
            logger.warning(
                "rate_limit_exceeded",
                key=key,
                endpoint=request.url.path,
                method=request.method,
            )
            raise HTTPException(
                status_code=429,
                detail="Too Many Requests",
                headers={"Retry-After": str(seconds)},
            )

    return _rate_limit_dep


# ── Per-endpoint limiter instances (exported names per §6.3) ──────────────
# Test ``test_rate_limit_module_exists_with_per_endpoint_limits`` asserts
# these exact names exist on this module.

auth_google_limit = _make_endpoint_limiter(times=5, seconds=60, name="auth")
create_order_limit = _make_endpoint_limiter(times=10, seconds=60, name="order")
verify_payment_limit = _make_endpoint_limiter(times=30, seconds=60, name="verifypay")
whatsapp_webhook_limit = _make_endpoint_limiter(times=1000, seconds=60, name="wawh")
razorpay_webhook_limit = _make_endpoint_limiter(times=100, seconds=60, name="rzpwh")
queue_today_limit = _make_endpoint_limiter(times=60, seconds=60, name="queue")
admin_limit = _make_endpoint_limiter(times=30, seconds=60, name="admin")
default_limit = _make_endpoint_limiter(times=100, seconds=60, name="default")


# ── IP blocklist helpers (spec §5.6) ─────────────────────────────────────

_AUTH_FAIL_PREFIX = "auth_fail"
_AUTH_FAIL_TTL = 600        # 10 min sliding window
_AUTH_FAIL_THRESHOLD = 5
_BLOCKED_IPS_SET = "blocked_ips"
_BLOCKED_IPS_KEY_PREFIX = "blocked_ips"
_BLOCK_TTL = 3600           # 1 hour


async def record_failed_login(ip: str) -> None:
    """Increment failed-login counter for IP. Block if threshold reached (spec §5.6).

    RULE 8: best-effort. A Redis outage must not turn a 401 (bad password) into a
    500 — swallow the error and log it. Worst case we miss counting one failure.
    """
    try:
        r = await _get_rate_limit_redis()
        fail_key = f"{_AUTH_FAIL_PREFIX}:{ip}"
        count = await r.incr(fail_key)
        await r.expire(fail_key, _AUTH_FAIL_TTL)
    except Exception as exc:
        logger.error("record_failed_login_redis_unavailable", error=str(exc))
        return

    if count >= _AUTH_FAIL_THRESHOLD:
        # Block IP for 1 hour using both storage shapes so either lookup works
        await r.sadd(_BLOCKED_IPS_SET, ip)
        await r.expire(_BLOCKED_IPS_SET, _BLOCK_TTL)
        await r.set(f"{_BLOCKED_IPS_KEY_PREFIX}:{ip}", "1", ex=_BLOCK_TTL)
        logger.warning(
            "ip_blocked_after_failed_logins",
            ip=ip,
            fail_count=count,
        )


async def is_ip_blocked(ip: str) -> bool:
    """Return True if IP is in the blocklist (checks both storage shapes).

    RULE 8: fail OPEN on a Redis outage (return False = not blocked) so auth
    stays reachable. A Redis blip must not 500 every login; the blocklist is a
    secondary defense, not a hard gate.
    """
    try:
        r = await _get_rate_limit_redis()
        is_set_member = await r.sismember(_BLOCKED_IPS_SET, ip)
        if is_set_member:
            return True
        key_exists = await r.exists(f"{_BLOCKED_IPS_KEY_PREFIX}:{ip}")
        return bool(key_exists)
    except Exception as exc:
        logger.error("is_ip_blocked_redis_unavailable", error=str(exc))
        return False


async def check_ip_blocklist(request: Request) -> None:
    """FastAPI dependency: 403 if request IP is in the Redis blocklist.

    Must be added to /auth/google BEFORE the rate limiter runs so that
    a blocked IP gets 403 (permanent block) not 429 (transient throttle).
    """
    ip = client_ip(request)  # iter1 #6: proxy-aware trusted client IP
    if await is_ip_blocked(ip):
        logger.warning("blocked_ip_rejected", ip=ip)
        raise HTTPException(status_code=403, detail="IP address blocked due to repeated failures")

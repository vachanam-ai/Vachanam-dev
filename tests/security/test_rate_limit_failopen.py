"""Regression: a Redis outage must NOT turn auth into a 500 wall (FIXLOG).

Root cause (prod 2026-06-23): Render's REDIS_URL was unreachable, so every
Redis-touching dependency (rate limiter, IP blocklist, failed-login counter)
raised and FastAPI returned 500 for EVERY auth route — signin was dead even
though the backend and DB were healthy.

Durable fix (RULE 8): the throttling layer fails OPEN — on a Redis error it
logs loudly and ALLOWS the request. Degraded throttling beats a total auth
outage. Token-locking for bookings stays fail-CLOSED elsewhere, so a Redis
blip can never double-book.

These tests simulate Redis-down by patching the Redis getter to raise.
"""
import pytest

from backend.middleware import rate_limit as rl

pytestmark = pytest.mark.asyncio


class _Req:
    headers: dict = {}
    method = "POST"

    class url:
        path = "/auth/login"

    class client:
        host = "8.8.8.8"


class _Resp:
    headers: dict = {}


async def _boom(*_a, **_k):
    raise ConnectionError("redis down")


async def test_rate_limit_dep_fails_open_when_redis_down(monkeypatch):
    # Limiter build / acquire goes through _get_rate_limit_redis → make it raise.
    monkeypatch.setattr(rl, "_get_rate_limit_redis", _boom)
    dep = rl._make_endpoint_limiter(times=5, seconds=60)
    # Must NOT raise (would surface as 500); returns None = request allowed.
    assert await dep(_Req(), _Resp()) is None


async def test_is_ip_blocked_fails_open_false_when_redis_down(monkeypatch):
    monkeypatch.setattr(rl, "_get_rate_limit_redis", _boom)
    # Fail-open: unknown blocklist state must read as "not blocked", not 500.
    assert await rl.is_ip_blocked("8.8.8.8") is False


async def test_check_ip_blocklist_does_not_raise_when_redis_down(monkeypatch):
    monkeypatch.setattr(rl, "_get_rate_limit_redis", _boom)
    # check_ip_blocklist must let the request through (no 403/500) on outage.
    assert await rl.check_ip_blocklist(_Req()) is None


async def test_record_failed_login_swallows_redis_error(monkeypatch):
    monkeypatch.setattr(rl, "_get_rate_limit_redis", _boom)
    # Best-effort: a Redis outage here must not convert a 401 into a 500.
    assert await rl.record_failed_login("8.8.8.8") is None


# ── client_ip behind Cloudflare (prod rate-limiter was silently disabled) ─────


class _CfReq:
    """Request with rotating Cloudflare-edge XFF + a stable CF-Connecting-IP."""

    def __init__(self, edge_ip, cf_ip="223.0.0.1"):
        self.headers = {
            "x-forwarded-for": f"223.0.0.1, {edge_ip}, 10.0.0.9",
            "cf-connecting-ip": cf_ip,
        }

        class _C:
            host = "10.0.0.9"

        self.client = _C()


def test_client_ip_prefers_cf_connecting_ip_and_is_stable(monkeypatch):
    # trusted_proxy_hops=2 would pick the rotating Cloudflare edge (XFF[-2]) →
    # a different key every request → counters never accumulate → no 429.
    # With CF-Connecting-IP preferred, the resolved IP is STABLE across requests.
    from backend.config import settings

    monkeypatch.setattr(settings, "trusted_proxy_hops", 2, raising=False)
    ip1 = rl.client_ip(_CfReq("162.158.54.36"))
    ip2 = rl.client_ip(_CfReq("172.71.124.143"))  # edge rotated
    assert ip1 == ip2 == "223.0.0.1"  # stable real client, not the edge


def test_client_ip_falls_back_to_hops_without_cf_header(monkeypatch):
    from backend.config import settings

    monkeypatch.setattr(settings, "trusted_proxy_hops", 2, raising=False)

    class _NoCf:
        headers = {"x-forwarded-for": "9.9.9.9, 1.1.1.1, 10.0.0.9"}

        class client:
            host = "10.0.0.9"

    # hops=2 → XFF[-2] = 1.1.1.1 (existing behaviour preserved when no CF header)
    assert rl.client_ip(_NoCf()) == "1.1.1.1"

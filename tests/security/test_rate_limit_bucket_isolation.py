"""Rate-limit bucket namespacing (FIXLOG #260).

Before the fix every endpoint limiter wrote ONE Redis ZSET per client key
(rl:ip:<ip>). The public /queue/{branch}/display TV board (unauthenticated →
IP-keyed, polling 24/7 from clinic WiFi) filled that shared ZSET, and login
from the same WiFi (also IP-keyed, 5/60) read it → every clinic login 429'd.
Buckets are now rl:<endpoint-name>:<key>.
"""
import pytest
from starlette.requests import Request

from backend.middleware.rate_limit import (
    _make_endpoint_limiter,
    auth_google_limit,
    queue_today_limit,
)

pytestmark = pytest.mark.asyncio


def _req(ip="10.9.8.7", path="/x"):
    scope = {
        "type": "http", "method": "GET", "path": path, "headers": [],
        "client": (ip, 1234), "query_string": b"", "scheme": "http",
        "server": ("testserver", 80),
    }
    return Request(scope)


class _Resp:  # the dep only needs the parameter to exist
    pass


async def test_tv_polling_does_not_consume_auth_budget(redis):
    """60 unauthenticated queue-display hits from one IP, then a login from
    the SAME IP: login must NOT be throttled (separate buckets)."""
    for _ in range(60):
        await queue_today_limit(_req(), _Resp())  # fills the queue bucket
    # queue bucket is now exhausted…
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await queue_today_limit(_req(), _Resp())
    assert exc.value.status_code == 429
    # …but the auth bucket for the SAME IP is untouched: 5 logins still pass.
    for _ in range(5):
        await auth_google_limit(_req(path="/auth/google"), _Resp())


async def test_named_limiters_use_distinct_buckets(redis):
    """Two limiters with different names never share a window."""
    a = _make_endpoint_limiter(times=2, seconds=60, name="iso_a")
    b = _make_endpoint_limiter(times=2, seconds=60, name="iso_b")
    await a(_req(), _Resp())
    await a(_req(), _Resp())
    # a is full; b for the same IP must still admit.
    await b(_req(), _Resp())

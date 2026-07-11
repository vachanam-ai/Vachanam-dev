"""Shared async Redis client — ONE per process/event-loop (FIXLOG #305).

Render's API instance began OOM-killing (512MB ceiling, ~every 2.5h) the day
#299 deployed. #299's wake_gate created a FRESH rediss:// client — TLS
context, connection pool, sockets — every 60s tick × 3 gated jobs, and the
auth middleware did the same on every authenticated request. Thousands of
short-lived TLS clients a day whose state lingered = the memory ramp.

One cached client fixes the leak and drops the per-connection AUTH/TLS
handshake overhead on Upstash (fewer billed commands, too).

Loop-aware because pytest creates a fresh event loop per test (TD-016's
original worry): a client bound to a dead loop raises "attached to a
different loop", so the cache keys on the running loop and rebuilds when it
changes. After a connection-level failure call drop() — fail-open callers
must not ride a poisoned socket forever.
"""
import asyncio

import redis.asyncio as aioredis

from backend.config import settings

_client: aioredis.Redis | None = None
_loop: asyncio.AbstractEventLoop | None = None


def get_redis() -> aioredis.Redis:
    """Cached client for the current event loop. Do NOT `async with` it or
    call aclose() — it is shared; closing it breaks every other caller."""
    global _client, _loop
    loop = asyncio.get_running_loop()
    if _client is None or _loop is not loop:
        # The previous loop's client (if any) is unreachable once its loop is
        # gone — it cannot be aclosed from here; GC reclaims it.
        _client = aioredis.from_url(settings.redis_url, decode_responses=True)
        _loop = loop
    return _client


def drop() -> None:
    """Forget the cached client so the next get_redis() rebuilds — call after
    a connection-level error (dead socket must not be reused forever)."""
    global _client, _loop
    _client = None
    _loop = None

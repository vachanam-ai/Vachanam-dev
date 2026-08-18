"""Pooler-safe distributed execution for in-process scheduled jobs.

Every web process may run APScheduler. A short Redis lease makes exactly one
process execute each job while avoiding PostgreSQL session advisory locks,
which are unsafe behind connection poolers such as Supavisor/PgBouncer.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any

import structlog

from backend.redis_client import get_redis

logger = structlog.get_logger()
LEASE_SECONDS = 180
_LOCAL_TICKS: dict[str, dict[str, Any]] = {}
_LOCAL_LOCKS: dict[str, asyncio.Lock] = {}
_REDIS_RETRY_AFTER = 0.0
_STARTED_AT = time.monotonic()
REDIS_RETRY_SECONDS = 300

_RENEW_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('expire', KEYS[1], ARGV[2])
end
return 0
"""
_RELEASE_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""


def _mark(job_id: str, status: str, **extra: Any) -> None:
    _LOCAL_TICKS[job_id] = {"status": status, "at_monotonic": time.monotonic(), **extra}


async def _renew_lease(key: str, owner: str, lease_seconds: int) -> None:
    redis = get_redis()
    while True:
        await asyncio.sleep(max(1, lease_seconds // 3))
        renewed = await redis.eval(_RENEW_LUA, 1, key, owner, lease_seconds)
        if not renewed:
            raise RuntimeError("scheduler lease ownership lost")


def leased_job(
    job_id: str,
    function: Callable[[], Awaitable[Any]],
    *,
    lease_seconds: int = LEASE_SECONDS,
) -> Callable[[], Awaitable[Any | None]]:
    """Wrap one scheduler coroutine in a renewable cross-process lease."""

    @wraps(function)
    async def run() -> Any | None:
        global _REDIS_RETRY_AFTER
        _mark(job_id, "tick")
        redis = None
        key = f"scheduler:lease:{job_id}"
        owner = uuid.uuid4().hex
        acquired = False
        lease_error: Exception | None = None
        distributed = os.getenv("SCHEDULER_DISTRIBUTED_LEASES", "false").lower() in {
            "1", "true", "yes",
        }
        if not distributed:
            lease_error = RuntimeError("distributed leases disabled")
        elif time.monotonic() >= _REDIS_RETRY_AFTER:
            try:
                redis = get_redis()
                acquired = bool(await redis.set(key, owner, nx=True, ex=lease_seconds))
            except Exception as exc:
                lease_error = exc
                _REDIS_RETRY_AFTER = time.monotonic() + REDIS_RETRY_SECONDS
                logger.error(
                    "scheduler_lease_unavailable_using_local_lock",
                    job=job_id,
                    error=str(exc)[:120],
                    retry_seconds=REDIS_RETRY_SECONDS,
                )
        else:
            lease_error = RuntimeError("redis lease circuit open")

        if lease_error is not None:
            # Render currently runs exactly one uvicorn worker on one instance.
            # Keeping its scheduler alive is safer than missing every reminder
            # and follow-up when Upstash is unavailable. The local lock still
            # prevents overlapping ticks in this process. Before horizontal
            # scaling, replace this fallback with a durable cross-instance
            # lease; render.yaml deliberately pins the current topology.
            local_lock = _LOCAL_LOCKS.setdefault(job_id, asyncio.Lock())
            if local_lock.locked():
                _mark(job_id, "contended_local")
                return None
            started = time.monotonic()
            async with local_lock:
                _mark(job_id, "running_local")
                try:
                    result = await function()
                except Exception as exc:
                    _mark(job_id, "error", error=type(exc).__name__)
                    logger.exception("scheduled_job_failed", job=job_id, lease="local")
                    raise
                _mark(
                    job_id,
                    "ok_local",
                    duration_ms=round((time.monotonic() - started) * 1000),
                )
                return result
        if not acquired:
            _mark(job_id, "contended")
            return None

        started = time.monotonic()
        _mark(job_id, "running")
        assert redis is not None
        renew_task = asyncio.create_task(_renew_lease(key, owner, lease_seconds))
        work_task = asyncio.create_task(function())
        try:
            done, _ = await asyncio.wait(
                {work_task, renew_task}, return_when=asyncio.FIRST_COMPLETED
            )
            if renew_task in done:
                # Lost ownership or Redis connectivity while work was still in
                # flight. Stop immediately; continuing could overlap the next
                # lease holder and duplicate a call or mutation.
                work_task.cancel()
                try:
                    await work_task
                except (asyncio.CancelledError, Exception):
                    pass
                error = renew_task.exception()
                raise error or RuntimeError("scheduler lease renewal stopped")
            result = await work_task
            _mark(job_id, "ok", duration_ms=round((time.monotonic() - started) * 1000))
            try:
                await redis.set(
                    f"scheduler:heartbeat:{job_id}",
                    json.dumps({"status": "ok", "at": time.time()}),
                    ex=7 * 86400,
                )
            except Exception:
                pass
            return result
        except Exception as exc:
            _mark(job_id, "error", error=type(exc).__name__)
            logger.exception("scheduled_job_failed", job=job_id)
            raise
        finally:
            if not work_task.done():
                work_task.cancel()
            renew_task.cancel()
            try:
                await renew_task
            except (asyncio.CancelledError, Exception):
                pass
            try:
                await redis.eval(_RELEASE_LUA, 1, key, owner)
            except Exception:
                pass

    return run


def local_scheduler_health(
    critical_jobs: tuple[str, ...] = (
        "pre_appt_reminder",
        "calendar_writer",
        "wa_delivery_queue",
    ),
    *,
    stale_after_seconds: int = 180,
) -> dict[str, Any]:
    """Dependency-free health snapshot for Render's /health probe."""
    now = time.monotonic()
    jobs: dict[str, Any] = {}
    healthy = True
    for job_id in critical_jobs:
        state = _LOCAL_TICKS.get(job_id)
        if state is None:
            age = now - _STARTED_AT
            status = "starting" if age <= stale_after_seconds else "missing"
        else:
            age = now - float(state["at_monotonic"])
            status = str(state["status"])
        job_ok = age <= stale_after_seconds and status not in {"lease_error", "error", "missing"}
        healthy = healthy and job_ok
        jobs[job_id] = {"status": status, "age_seconds": round(age, 1)}
    return {"ok": healthy, "jobs": jobs}

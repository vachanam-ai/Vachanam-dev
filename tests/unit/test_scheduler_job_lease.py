import inspect
import time

import pytest

import backend.jobs.job_lease as lease


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.fail_set = False

    async def set(self, key, value, **options):
        if self.fail_set:
            raise ConnectionError("redis unavailable")
        if options.get("nx") and key in self.values:
            return None
        self.values[key] = value
        return True

    async def eval(self, script, _count, key, owner, *args):
        if self.values.get(key) != owner:
            return 0
        if "del" in script:
            del self.values[key]
        return 1


@pytest.mark.asyncio
async def test_job_executes_and_releases_owned_lease(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(lease, "get_redis", lambda: redis)
    calls = []

    async def work():
        calls.append("ran")
        return 7

    assert await lease.leased_job("reminder-test", work, lease_seconds=30)() == 7
    assert calls == ["ran"]
    assert "scheduler:lease:reminder-test" not in redis.values
    assert lease._LOCAL_TICKS["reminder-test"]["status"] == "ok"


@pytest.mark.asyncio
async def test_contended_lease_skips_duplicate_execution(monkeypatch):
    redis = FakeRedis()
    redis.values["scheduler:lease:reminder-test"] = "other-process"
    monkeypatch.setattr(lease, "get_redis", lambda: redis)
    called = False

    async def work():
        nonlocal called
        called = True

    assert await lease.leased_job("reminder-test", work)() is None
    assert called is False
    assert lease._LOCAL_TICKS["reminder-test"]["status"] == "contended"


@pytest.mark.asyncio
async def test_redis_failure_runs_once_under_local_lock(monkeypatch):
    redis = FakeRedis()
    redis.fail_set = True
    monkeypatch.setattr(lease, "get_redis", lambda: redis)
    monkeypatch.setattr(lease, "_REDIS_RETRY_AFTER", 0.0)
    called = 0

    async def work():
        nonlocal called
        called += 1
        return 9

    assert await lease.leased_job("reminder-test", work)() == 9
    assert called == 1
    assert lease._LOCAL_TICKS["reminder-test"]["status"] == "ok_local"


@pytest.mark.asyncio
async def test_redis_circuit_avoids_repeated_quota_calls(monkeypatch):
    redis = FakeRedis()
    redis.fail_set = True
    attempts = 0

    async def counted_set(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        raise ConnectionError("quota exhausted")

    redis.set = counted_set
    monkeypatch.setattr(lease, "get_redis", lambda: redis)
    monkeypatch.setattr(lease, "_REDIS_RETRY_AFTER", 0.0)

    async def work():
        return None

    await lease.leased_job("first", work)()
    await lease.leased_job("second", work)()
    assert attempts == 1
    assert lease._LOCAL_TICKS["first"]["status"] == "ok_local"
    assert lease._LOCAL_TICKS["second"]["status"] == "ok_local"


def test_health_detects_stale_or_failed_critical_jobs(monkeypatch):
    now = time.monotonic()
    monkeypatch.setattr(
        lease,
        "_LOCAL_TICKS",
        {
            "pre_appt_reminder": {"status": "ok", "at_monotonic": now},
            "calendar_writer": {"status": "contended", "at_monotonic": now},
            "wa_delivery_queue": {"status": "lease_error", "at_monotonic": now},
        },
    )
    snapshot = lease.local_scheduler_health()
    assert snapshot["ok"] is False
    assert snapshot["jobs"]["wa_delivery_queue"]["status"] == "lease_error"


def test_main_has_no_pooler_unsafe_session_leader_lock():
    import backend.main as main

    source = inspect.getsource(main.lifespan)
    assert "pg_try_advisory_lock" not in source
    assert "scheduler_started_with_distributed_job_leases" in source
    assert '"pre_appt_reminder"' in source
    assert 'options["next_run_time"]' in source

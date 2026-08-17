"""#299 follow-up: /health must report WHICH commit is running.

The whole cost fix lives in the API process's schedulers, so "did the push
actually redeploy?" is a question we must be able to answer from outside.
Render sets RENDER_GIT_COMMIT; without this marker there is no external signal.
"""
from fastapi.testclient import TestClient


def _client():
    import backend.main as m
    return TestClient(m.app)


def test_health_omits_build_when_not_on_render(monkeypatch):
    monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
    body = _client().get("/health").json()
    assert body["status"] == "ok"
    assert "build" not in body  # local/dev: nothing to report


def test_health_reports_short_commit_on_render(monkeypatch):
    monkeypatch.setenv("RENDER_GIT_COMMIT", "9365b89abcdef0123456789")
    body = _client().get("/health").json()
    assert body["build"] == "9365b89"          # short SHA only
    assert len(body["build"]) == 7             # never the full hash
    assert body["status"] == "ok"


def test_memstat_returns_none_or_valid_shape():
    """memstat must never raise — health path. Off-Linux it returns None;
    on Linux a dict with rss/peak MB ints."""
    from backend.memstat import process_mem_mb

    mem = process_mem_mb()
    assert mem is None or (
        isinstance(mem["rss"], int) and mem["rss"] > 0 and "peak" in mem
    )


def test_memstat_parses_proc_format(tmp_path, monkeypatch):
    """Parse a canned /proc/self/status so the Linux path is covered on any OS."""
    import builtins

    import backend.memstat as ms

    fake = tmp_path / "status"
    fake.write_text("Name:\tx\nVmHWM:\t  409600 kB\nVmRSS:\t  204800 kB\n")
    real_open = builtins.open
    monkeypatch.setattr(
        builtins, "open",
        lambda p, *a, **k: real_open(fake if p == "/proc/self/status" else p, *a, **k),
    )
    assert ms.process_mem_mb() == {"rss": 200, "peak": 400}


# ── SEC #7/#11: diagnostic endpoints gated in production ──────────────────

def test_diagnostics_open_in_dev(monkeypatch):
    import backend.config as cfg
    monkeypatch.setattr(cfg.settings, "app_env", "development")
    r = _client().get("/health/ratelimit")
    assert r.status_code == 200  # dev: open for debugging


def test_diagnostics_require_admin_in_prod(monkeypatch):
    import backend.config as cfg
    monkeypatch.setattr(cfg.settings, "app_env", "production")
    c = _client()
    for url in ("/health/ratelimit", "/health/voice-plane", "/health/redis"):
        r = c.get(url)
        assert r.status_code == 401, f"{url} leaked recon unauthenticated in prod"
    # a non-admin token is still rejected
    import uuid
    from datetime import datetime, timedelta, timezone

    import jwt
    tok = jwt.encode({
        "sub": str(uuid.uuid4()), "email": "o@c.com", "role": "org_admin",
        "org_id": str(uuid.uuid4()), "branch_ids": [], "is_admin": False,
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
        "jti": str(uuid.uuid4())},
        cfg.settings.jwt_secret, algorithm="HS256")
    r = c.get("/health/ratelimit", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 403, "non-admin reached prod diagnostics"


def _tick_critical_jobs(monkeypatch, *, status: str = "ok"):
    """Give this process the scheduler ticks a real API process would have.

    /health/readiness returns 503 when the critical jobs stop ticking. Render's
    liveness path remains 200 to avoid a dependency-driven restart loop. In a test
    process no scheduler ever runs, so the jobs read "starting" for 180s and
    "missing" after that — meaning this test passed alone (2s) and failed
    inside the full suite (26 min), purely on elapsed wall-clock time
    (2026-08-12). Pin the state instead of racing it.
    """
    from backend.jobs import job_lease

    ticks = dict(job_lease._LOCAL_TICKS)
    monkeypatch.setattr(job_lease, "_LOCAL_TICKS", ticks)
    for job_id in ("pre_appt_reminder", "calendar_writer", "wa_delivery_queue"):
        job_lease._mark(job_id, status)
    return ticks


def test_public_health_still_open_in_prod(monkeypatch):
    """UptimeRobot must still get an unauthenticated 200 from /health itself."""
    import backend.config as cfg
    monkeypatch.setattr(cfg.settings, "app_env", "production")
    _tick_critical_jobs(monkeypatch)
    r = _client().get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_prod_liveness_stays_up_while_readiness_reports_stale_scheduler(monkeypatch):
    import time

    import backend.config as cfg

    monkeypatch.setattr(cfg.settings, "app_env", "production")
    ticks = _tick_critical_jobs(monkeypatch)
    # Age every tick past the 180s staleness ceiling.
    for state in ticks.values():
        state["at_monotonic"] = time.monotonic() - 10_000

    live = _client().get("/health")
    ready = _client().get("/health/readiness")
    assert live.status_code == 200
    assert ready.status_code == 503
    body = ready.json()
    assert body["status"] == "degraded"
    assert body["scheduler"]["ok"] is False


def test_a_failing_job_status_is_degraded_even_when_fresh(monkeypatch):
    """Staleness is not the only failure: a job ticking with an error status
    is still a dead reminder pipeline."""
    import backend.config as cfg

    monkeypatch.setattr(cfg.settings, "app_env", "production")
    _tick_critical_jobs(monkeypatch, status="lease_error")
    assert _client().get("/health").status_code == 200
    r = _client().get("/health/readiness")
    assert r.status_code == 503
    assert r.json()["scheduler"]["ok"] is False

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

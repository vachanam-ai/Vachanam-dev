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

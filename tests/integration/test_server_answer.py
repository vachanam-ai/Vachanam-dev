import pytest
import re
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr("backend.config.settings.recording_enabled", True)
    monkeypatch.setattr("backend.config.settings.public_url", "https://agent-dev.vachanam.in")
    from agent.server import app
    return TestClient(app)


def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_answer_returns_valid_xml(client):
    r = client.post("/answer", data={"From": "+919999999999", "To": "+918046733493", "CallSid": "abc"})
    assert r.status_code == 200
    assert "application/xml" in r.headers["content-type"] or "text/xml" in r.headers["content-type"]
    body = r.text
    assert "<Response>" in body
    assert "<Stream" in body
    assert 'bidirectional="true"' in body
    assert 'contentType="audio/x-mulaw;rate=8000"' in body
    assert "wss://agent-dev.vachanam.in/ws" in body


def test_answer_includes_record_when_enabled(client):
    r = client.post("/answer", data={"From": "+919999999999", "To": "+918046733493", "CallSid": "abc"})
    assert "<Record" in r.text
    assert "/recording-finished" in r.text


def test_answer_omits_record_when_disabled(monkeypatch):
    monkeypatch.setattr("backend.config.settings.recording_enabled", False)
    from agent.server import app
    c = TestClient(app)
    r = c.post("/answer", data={"From": "+919999999999", "To": "+918046733493", "CallSid": "abc"})
    assert "<Record" not in r.text

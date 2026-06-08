import pytest
import re
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr("backend.config.settings.recording_enabled", True)
    monkeypatch.setattr("backend.config.settings.public_url", "https://agent-dev.vachanam.in")
    # Default: helper returns None so existing tests are unaffected by DB lookup
    import agent.server as server_mod
    monkeypatch.setattr(
        server_mod,
        "resolve_branch_name_for_did",
        lambda did: _async_return(None),
    )
    from agent.server import app
    return TestClient(app)


async def _async_return(value):
    """Minimal async wrapper for monkeypatching coroutine-returning helpers."""
    return value


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


def test_answer_xml_is_wellformed(client):
    import xml.etree.ElementTree as ET
    r = client.post("/answer", data={"From": "+919999999999", "To": "+918046733493", "CallSid": "abc"})
    # Must parse without raising
    root = ET.fromstring(r.text)
    assert root.tag == "Response"
    # Stream child must exist and its text must contain wss://
    stream = root.find("Stream")
    assert stream is not None
    assert "wss://agent-dev.vachanam.in/ws" in stream.text
    # Query separators in the URL must be present as literal & after XML decoding (which ET.fromstring does)
    assert "&to=" in stream.text
    assert "&from=" in stream.text


def test_answer_uses_clinic_name_when_branch_resolved(monkeypatch):
    """When resolve_branch_name_for_did returns a clinic name,
    the <Speak> element must contain that name in the welcome message."""
    monkeypatch.setattr("backend.config.settings.recording_enabled", False)
    monkeypatch.setattr("backend.config.settings.public_url", "https://agent-dev.vachanam.in")
    import agent.server as server_mod
    monkeypatch.setattr(
        server_mod,
        "resolve_branch_name_for_did",
        lambda did: _async_return("Pytest Clinic"),
    )
    from agent.server import app
    c = TestClient(app)
    r = c.post("/answer", data={"From": "+919999999999", "To": "+918046733493", "CallSid": "abc"})
    assert r.status_code == 200
    assert "Pytest Clinic" in r.text
    assert "నమస్కారం" in r.text
    assert "స్వాగతం" in r.text


def test_answer_falls_back_when_branch_not_found(monkeypatch):
    """When resolve_branch_name_for_did returns None,
    the <Speak> element must contain the generic Telugu hold message."""
    monkeypatch.setattr("backend.config.settings.recording_enabled", False)
    monkeypatch.setattr("backend.config.settings.public_url", "https://agent-dev.vachanam.in")
    import agent.server as server_mod
    monkeypatch.setattr(
        server_mod,
        "resolve_branch_name_for_did",
        lambda did: _async_return(None),
    )
    from agent.server import app
    c = TestClient(app)
    r = c.post("/answer", data={"From": "+919999999999", "To": "+918046733493", "CallSid": "abc"})
    assert r.status_code == 200
    assert "దయచేసి ఒక్క క్షణం వేచి ఉండండి" in r.text
    assert "Pytest Clinic" not in r.text

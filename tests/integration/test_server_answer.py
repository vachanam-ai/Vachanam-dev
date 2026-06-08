"""Integration tests for agent/server.py /answer and /ws endpoints.

Contract: Vobiz calls /answer with query param CallUUID (NOT Twilio Form fields).
Reference: https://github.com/vobiz-ai/Vobiz-X-Pipecat/blob/master/server.py

TDD: these tests were written against the NEW Vobiz contract BEFORE the
production code was updated (red → green discipline).
"""
import pytest
import re
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr("backend.config.settings.recording_enabled", True)
    monkeypatch.setattr("backend.config.settings.public_url", "https://agent-dev.vachanam.in")
    monkeypatch.setattr("backend.config.settings.vobiz_did_number", "+918046733493")
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
    """Vobiz sends CallUUID as a query param — not Twilio Form fields."""
    r = client.post("/answer", params={"CallUUID": "abc"})
    assert r.status_code == 200
    assert "application/xml" in r.headers["content-type"] or "text/xml" in r.headers["content-type"]
    body = r.text
    assert "<Response>" in body
    assert "<Stream" in body
    assert 'bidirectional="true"' in body
    assert 'contentType="audio/x-mulaw;rate=8000"' in body
    assert "wss://agent-dev.vachanam.in/ws" in body


def test_answer_includes_record_when_enabled(client):
    r = client.post("/answer", params={"CallUUID": "abc"})
    assert "<Record" in r.text
    assert "/recording-ready" in r.text


def test_answer_omits_record_when_disabled(monkeypatch):
    monkeypatch.setattr("backend.config.settings.recording_enabled", False)
    monkeypatch.setattr("backend.config.settings.public_url", "https://agent-dev.vachanam.in")
    monkeypatch.setattr("backend.config.settings.vobiz_did_number", "+918046733493")
    import agent.server as server_mod
    monkeypatch.setattr(
        server_mod,
        "resolve_branch_name_for_did",
        lambda did: _async_return(None),
    )
    from agent.server import app
    c = TestClient(app)
    r = c.post("/answer", params={"CallUUID": "abc"})
    assert "<Record" not in r.text


def test_answer_xml_is_wellformed(client):
    """Stream URL must be bare — no query params (?call_id=&to=&from=) appended."""
    import xml.etree.ElementTree as ET
    r = client.post("/answer", params={"CallUUID": "abc"})
    root = ET.fromstring(r.text)
    assert root.tag == "Response"
    stream = root.find("Stream")
    assert stream is not None
    # WS URL is bare — Vobiz reads caller identity from the start event
    assert "wss://agent-dev.vachanam.in/ws" in stream.text
    # Must NOT contain old Twilio-style query params
    assert "?call_id=" not in stream.text
    assert "&to=" not in stream.text
    assert "&from=" not in stream.text


def test_answer_uses_clinic_name_when_branch_resolved(monkeypatch):
    """When resolve_branch_name_for_did returns a clinic name,
    the <Speak> element must contain that name in the welcome message."""
    monkeypatch.setattr("backend.config.settings.recording_enabled", False)
    monkeypatch.setattr("backend.config.settings.public_url", "https://agent-dev.vachanam.in")
    monkeypatch.setattr("backend.config.settings.vobiz_did_number", "+918046733493")
    import agent.server as server_mod
    monkeypatch.setattr(
        server_mod,
        "resolve_branch_name_for_did",
        lambda did: _async_return("Pytest Clinic"),
    )
    from agent.server import app
    c = TestClient(app)
    r = c.post("/answer", params={"CallUUID": "abc"})
    assert r.status_code == 200
    assert "Pytest Clinic" in r.text
    assert "నమస్కారం" in r.text
    assert "స్వాగతం" in r.text


def test_answer_falls_back_when_branch_not_found(monkeypatch):
    """When resolve_branch_name_for_did returns None,
    the <Speak> element must contain the SaaS-branded Vachanam greeting."""
    monkeypatch.setattr("backend.config.settings.recording_enabled", False)
    monkeypatch.setattr("backend.config.settings.public_url", "https://agent-dev.vachanam.in")
    monkeypatch.setattr("backend.config.settings.vobiz_did_number", "+918046733493")
    import agent.server as server_mod
    monkeypatch.setattr(
        server_mod,
        "resolve_branch_name_for_did",
        lambda did: _async_return(None),
    )
    from agent.server import app
    c = TestClient(app)
    r = c.post("/answer", params={"CallUUID": "abc"})
    assert r.status_code == 200
    assert "Vachanam" in r.text
    assert "నమస్కారం" in r.text
    assert "స్వాగతం" in r.text
    assert "Pytest Clinic" not in r.text


def test_answer_speak_uses_vachanam_branding(client):
    """Default fixture stubs resolve_branch_name_for_did to None — verify
    the SaaS Vachanam-branded greeting is emitted on the pickup XML."""
    r = client.post("/answer", params={"CallUUID": "abc"})
    assert r.status_code == 200
    assert "Vachanam" in r.text
    assert "నమస్కారం" in r.text
    assert "స్వాగతం" in r.text


# ── New tests for Vobiz-specific contract ──────────────────────────────────────


def test_answer_accepts_get(monkeypatch):
    """Vobiz may use GET depending on app config — must return 200 + XML on GET."""
    monkeypatch.setattr("backend.config.settings.recording_enabled", False)
    monkeypatch.setattr("backend.config.settings.public_url", "https://agent-dev.vachanam.in")
    monkeypatch.setattr("backend.config.settings.vobiz_did_number", "+918046733493")
    import agent.server as server_mod
    monkeypatch.setattr(
        server_mod,
        "resolve_branch_name_for_did",
        lambda did: _async_return(None),
    )
    from agent.server import app
    c = TestClient(app)
    r = c.get("/answer", params={"CallUUID": "abc"})
    assert r.status_code == 200
    assert "application/xml" in r.headers["content-type"] or "text/xml" in r.headers["content-type"]
    assert "<Response>" in r.text
    assert "<Stream" in r.text


def test_answer_includes_vobiz_stream_attrs(client):
    """Stream tag must include audioTrack="inbound" and keepCallAlive="true"
    per the official Vobiz-X-Pipecat reference repo."""
    r = client.post("/answer", params={"CallUUID": "abc"})
    assert r.status_code == 200
    assert 'audioTrack="inbound"' in r.text
    assert 'keepCallAlive="true"' in r.text


def test_answer_record_uses_callbackUrl(client):
    """Record tag must use callbackUrl + callbackMethod (Vobiz naming),
    NOT Twilio-style 'action' attribute."""
    r = client.post("/answer", params={"CallUUID": "abc"})
    assert r.status_code == 200
    assert "<Record" in r.text
    assert "callbackUrl" in r.text
    assert "callbackMethod" in r.text
    # Must NOT use the old Twilio 'action' attribute name
    assert 'action="' not in r.text

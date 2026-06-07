"""Integration tests for GET /transfer-emergency/{call_id} in agent/server.py.

TDD Step 1 (Task 8): write tests before implementation.
These must FAIL before the real endpoint replaces the 501 stub.
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client_with_signal(monkeypatch):
    """Client with a pre-set transfer signal for CALL_TEST_ABC and a stubbed resolver."""
    from agent import server

    # Reset signal map to known state
    server._transfer_signals.clear()
    server._transfer_signals["CALL_TEST_ABC"] = True

    # Stub branch resolver so test doesn't need DB
    async def fake_resolve(call_id: str) -> str | None:
        return "+919876543210" if call_id == "CALL_TEST_ABC" else None

    monkeypatch.setattr(server, "resolve_branch_emergency_contact", fake_resolve)
    return TestClient(server.app)


def test_transfer_emergency_returns_dial_xml_for_signalled_call(client_with_signal):
    """GET /transfer-emergency/{call_id} must return XML with <Dial> when signal is set."""
    r = client_with_signal.get("/transfer-emergency/CALL_TEST_ABC")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    ct = r.headers.get("content-type", "")
    assert "application/xml" in ct or "text/xml" in ct, (
        f"Expected XML content-type, got: {ct!r}"
    )
    assert "<Dial>+919876543210</Dial>" in r.text, (
        f"Expected <Dial> with emergency contact, got: {r.text!r}"
    )
    assert "<Response>" in r.text


def test_transfer_emergency_404_for_unsignalled_call(client_with_signal):
    """GET /transfer-emergency/{call_id} must return 404 when no signal is set for call_id."""
    r = client_with_signal.get("/transfer-emergency/CALL_UNKNOWN")
    assert r.status_code == 404, f"Expected 404 for unknown call, got {r.status_code}"

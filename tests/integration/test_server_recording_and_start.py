"""
tests/integration/test_server_recording_and_start.py

Task 10 — recording callbacks + outbound /start endpoint.

3 tests:
  test_recording_finished_logs_and_200s      — POST form, always 200
  test_recording_ready_downloads_mp3          — aiohttp mocked; sentinel file asserted
  test_start_returns_call_id                  — aiohttp mocked; upstream call_id propagated

All aiohttp calls are mocked — NO real network I/O in tests (guardrail 7).
"""
from __future__ import annotations

import asyncio
import io
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Shared fixture — patch settings before server is imported
# ---------------------------------------------------------------------------

@pytest.fixture()
def client(monkeypatch, tmp_path):
    """TestClient with settings patched and recordings dir pointing to tmp_path."""
    monkeypatch.setattr("backend.config.settings.recording_enabled", True)
    monkeypatch.setattr("backend.config.settings.public_url", "https://agent-dev.vachanam.in")
    monkeypatch.setattr("backend.config.settings.vobiz_auth_id", "AID_TEST")
    monkeypatch.setattr("backend.config.settings.vobiz_auth_token", "ATK_SECRET")
    monkeypatch.setattr("backend.config.settings.vobiz_did_number", "+914000000000")
    # Redirect recordings dir so no files land in repo tree
    import agent.server as server_mod
    monkeypatch.setattr(server_mod, "_RECORDINGS_DIR", tmp_path)
    from agent.server import app
    return TestClient(app)


# ---------------------------------------------------------------------------
# Helpers: async context-manager mocks for aiohttp
# ---------------------------------------------------------------------------

class _FakeResponse:
    """Simulates aiohttp.ClientResponse for GET (recording download)."""

    def __init__(self, content: bytes, status: int = 200) -> None:
        self._content = content
        self.status = status

    async def read(self) -> bytes:
        return self._content

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise Exception(f"HTTP {self.status}")

    async def __aenter__(self) -> "_FakeResponse":
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass

    async def json(self) -> dict:
        import json
        return json.loads(self._content)


class _FakePostResponse:
    """Simulates aiohttp.ClientResponse for POST (outbound call)."""

    def __init__(self, body: dict, status: int = 200) -> None:
        self._body = body
        self.status = status

    async def json(self) -> dict:
        return self._body

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise Exception(f"HTTP {self.status}")

    async def __aenter__(self) -> "_FakePostResponse":
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass


class _FakeSession:
    """
    Minimal aiohttp.ClientSession mock — supports .get() and .post() as
    async context managers. Instantiated as `async with _FakeSession() as sess`.
    """

    def __init__(self, get_response: Any = None, post_response: Any = None) -> None:
        self._get_response = get_response
        self._post_response = post_response

    def get(self, url: str, **kwargs: Any) -> Any:
        return self._get_response

    def post(self, url: str, **kwargs: Any) -> Any:
        return self._post_response

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass


# ---------------------------------------------------------------------------
# Test 1: /recording-finished always returns 200 and logs
# ---------------------------------------------------------------------------

def test_recording_finished_logs_and_200s(client):
    """POST form with CallSid + duration must return 200 with ok=true."""
    r = client.post(
        "/recording-finished",
        data={"CallSid": "CALL_ABC123", "duration": "42"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body.get("ok") is True


def test_recording_finished_200s_even_when_recording_disabled(monkeypatch, tmp_path):
    """
    RECORDING_ENABLED=false: /recording-finished still returns 200 so Vobiz
    does not retry. This exercises the 'gated but always-200' guardrail.
    """
    monkeypatch.setattr("backend.config.settings.recording_enabled", False)
    import agent.server as server_mod
    monkeypatch.setattr(server_mod, "_RECORDINGS_DIR", tmp_path)
    from agent.server import app
    c = TestClient(app)
    r = c.post(
        "/recording-finished",
        data={"CallSid": "CALL_DISABLED", "duration": "10"},
    )
    assert r.status_code == 200
    assert r.json().get("ok") is True


# ---------------------------------------------------------------------------
# Test 2: /recording-ready downloads MP3 and writes sentinel file
# ---------------------------------------------------------------------------

def test_recording_ready_downloads_mp3(client, tmp_path, monkeypatch):
    """
    Mock aiohttp GET to return sentinel bytes. Assert the file is written to
    the redirected recordings dir as CALL_DL_XYZ.mp3.
    """
    sentinel = b"ID3_FAKE_MP3_CONTENT"
    fake_get_resp = _FakeResponse(content=sentinel)
    fake_session = _FakeSession(get_response=fake_get_resp)

    import aiohttp
    monkeypatch.setattr(aiohttp, "ClientSession", lambda: fake_session)

    r = client.post(
        "/recording-ready",
        data={"CallSid": "CALL_DL_XYZ", "recording_url": "https://cdn.vobiz.ai/rec/CALL_DL_XYZ.mp3"},
    )
    assert r.status_code == 200
    assert r.json().get("ok") is True

    # Assert file written in redirected tmp dir
    expected_path = tmp_path / "CALL_DL_XYZ.mp3"
    assert expected_path.exists(), f"Expected file not found: {expected_path}"
    assert expected_path.read_bytes() == sentinel


def test_recording_ready_skipped_when_disabled(monkeypatch, tmp_path):
    """No download when RECORDING_ENABLED=false. Still returns 200."""
    monkeypatch.setattr("backend.config.settings.recording_enabled", False)
    import agent.server as server_mod
    monkeypatch.setattr(server_mod, "_RECORDINGS_DIR", tmp_path)
    from agent.server import app
    c = TestClient(app)

    r = c.post(
        "/recording-ready",
        data={"CallSid": "CALL_SKIP", "recording_url": "https://cdn.vobiz.ai/rec/CALL_SKIP.mp3"},
    )
    assert r.status_code == 200
    # File must NOT exist (no download attempted)
    assert not (tmp_path / "CALL_SKIP.mp3").exists()


def test_recording_ready_rejects_path_traversal(client, monkeypatch):
    """CallSid with ../ characters must be rejected with 400 (guardrail 2)."""
    r = client.post(
        "/recording-ready",
        data={"CallSid": "../evil", "recording_url": "https://cdn.vobiz.ai/rec/x.mp3"},
    )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Test 3: /start returns upstream call_id
# ---------------------------------------------------------------------------

def test_start_returns_call_id(client, monkeypatch):
    """
    Mock aiohttp POST to Vobiz API. POST {"to": "+919876543210"} must return
    200 and include the upstream call_id.
    """
    vobiz_payload = {"call_id": "VOBIZ_CID_9999", "status": "queued"}
    fake_post_resp = _FakePostResponse(body=vobiz_payload, status=200)
    fake_session = _FakeSession(post_response=fake_post_resp)

    import aiohttp
    monkeypatch.setattr(aiohttp, "ClientSession", lambda: fake_session)

    r = client.post("/start", json={"to": "+919876543210"})
    assert r.status_code == 200
    body = r.json()
    assert body.get("call_id") == "VOBIZ_CID_9999"


def test_start_rejects_missing_to(client):
    """Empty 'to' field must return 400."""
    r = client.post("/start", json={"to": ""})
    assert r.status_code == 400


def test_start_rejects_non_e164(client):
    """'to' without leading '+' must return 400 (E.164 guardrail)."""
    r = client.post("/start", json={"to": "09876543210"})
    assert r.status_code == 400

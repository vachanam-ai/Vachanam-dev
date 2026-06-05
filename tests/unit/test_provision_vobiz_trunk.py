"""Unit tests for scripts/provision_vobiz_trunk.py.

All tests use mocks only — no real network calls, no real LiveKit, no real Vobiz.
"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure project root is on path so the script's sys.path.insert works correctly
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

# Import the functions under test directly (not __main__)
from scripts.provision_vobiz_trunk import (
    _validate_env,
    derive_livekit_sip_uri,
    patch_vobiz_inbound_destination,
    provision_outbound_trunk,
)


# ── Test 1: refuses to run when a required env var is missing ───────────────


def test_refuses_with_missing_env(monkeypatch):
    """Script must sys.exit(1) and name VOBIZ_SIP_DOMAIN when it's absent."""
    # Clear ALL required vars from environment
    required = [
        "VOBIZ_SIP_DOMAIN",
        "VOBIZ_SIP_USERNAME",
        "VOBIZ_SIP_PASSWORD",
        "VOBIZ_DID_NUMBER",
        "VOBIZ_PARTNER_AUTH_ID",
        "VOBIZ_PARTNER_AUTH_TOKEN",
        "VOBIZ_TRUNK_ID",
        "LIVEKIT_URL",
        "LIVEKIT_API_KEY",
        "LIVEKIT_API_SECRET",
    ]
    for var in required:
        monkeypatch.delenv(var, raising=False)

    # Leaving VOBIZ_SIP_DOMAIN absent — _validate_env should exit(1)
    with pytest.raises(SystemExit) as exc_info:
        _validate_env()

    assert exc_info.value.code == 1


def test_refuses_names_each_missing_var(monkeypatch, capsys):
    """Error output must mention VOBIZ_SIP_DOMAIN when it's the only missing var."""
    # Set all required vars except VOBIZ_SIP_DOMAIN
    monkeypatch.setenv("VOBIZ_SIP_USERNAME", "testuser")
    monkeypatch.setenv("VOBIZ_SIP_PASSWORD", "testpass")
    monkeypatch.setenv("VOBIZ_DID_NUMBER", "+914066000042")
    monkeypatch.setenv("VOBIZ_PARTNER_AUTH_ID", "auth_id_123")
    monkeypatch.setenv("VOBIZ_PARTNER_AUTH_TOKEN", "auth_token_456")
    monkeypatch.setenv("VOBIZ_TRUNK_ID", "trunk_789")
    monkeypatch.setenv("LIVEKIT_URL", "wss://vachanam-agent.fly.dev")
    monkeypatch.setenv("LIVEKIT_API_KEY", "apikey")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "apisecret")
    monkeypatch.delenv("VOBIZ_SIP_DOMAIN", raising=False)

    with pytest.raises(SystemExit) as exc_info:
        _validate_env()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "VOBIZ_SIP_DOMAIN" in captured.err


# ── Test 2: idempotent — skips create when outbound trunk already exists ─────


@pytest.mark.asyncio
async def test_idempotent_skips_existing_outbound_trunk():
    """provision_outbound_trunk must NOT call create_sip_outbound_trunk
    when a trunk named 'Vachanam-Vobiz' already exists in the list response."""

    # Build a fake trunk that matches the name
    existing_trunk = MagicMock()
    existing_trunk.sip_trunk_id = "TR_existing_abc123"
    existing_trunk.name = "Vachanam-Vobiz"
    existing_trunk.address = "abc123.sip.vobiz.ai"
    existing_trunk.auth_username = "testuser"

    list_response = MagicMock()
    list_response.items = [existing_trunk]

    mock_sip = MagicMock()
    mock_sip.list_outbound_trunk = AsyncMock(return_value=list_response)
    mock_sip.create_outbound_trunk = AsyncMock()

    mock_lk = MagicMock()
    mock_lk.sip = mock_sip

    trunk_id = await provision_outbound_trunk(
        lk=mock_lk,
        sip_domain="abc123.sip.vobiz.ai",
        sip_username="testuser",
        sip_password="testpass",
        did_number="+914066000042",
    )

    # Must return the existing trunk ID
    assert trunk_id == "TR_existing_abc123"
    # Must NOT have called create
    mock_sip.create_outbound_trunk.assert_not_called()


# ── Test 3: LiveKit SIP URI derivation ──────────────────────────────────────


def test_livekit_sip_uri_derivation_wss():
    """wss:// scheme must be stripped, leaving bare hostname."""
    result = derive_livekit_sip_uri("wss://vachanam-agent.fly.dev")
    assert result == "vachanam-agent.fly.dev"


def test_livekit_sip_uri_derivation_ws():
    """ws:// scheme must be stripped."""
    result = derive_livekit_sip_uri("ws://vachanam-agent.fly.dev")
    assert result == "vachanam-agent.fly.dev"


def test_livekit_sip_uri_derivation_https():
    """https:// scheme must be stripped."""
    result = derive_livekit_sip_uri("https://vachanam-agent.fly.dev")
    assert result == "vachanam-agent.fly.dev"


def test_livekit_sip_uri_derivation_trailing_slash():
    """Trailing slash must not appear in the result."""
    result = derive_livekit_sip_uri("wss://vachanam-agent.fly.dev/")
    assert result == "vachanam-agent.fly.dev"


def test_livekit_sip_uri_no_sip_prefix():
    """Result must never start with 'sip:' — Vobiz doc says no prefix."""
    result = derive_livekit_sip_uri("wss://vachanam-agent.fly.dev")
    assert not result.startswith("sip:")
    assert not result.startswith("wss:")
    assert not result.startswith("ws:")


# ── Test 4: Vobiz auth scheme uses X-Auth-ID + X-Auth-Token (not Bearer) ────


@pytest.mark.asyncio
async def test_patch_vobiz_uses_x_auth_headers_on_skip():
    """GET call must use X-Auth-ID / X-Auth-Token, never Authorization: Bearer.

    When inbound_destination already matches, PATCH is skipped — this test
    captures the headers sent on the GET request.
    """
    get_json = {"inbound_destination": "vachanam-agent.fly.dev"}

    mock_get_response = MagicMock()
    mock_get_response.raise_for_status = MagicMock()
    mock_get_response.json = MagicMock(return_value=get_json)
    mock_get_response.status_code = 200

    captured_headers: list[dict] = []

    async def fake_get(url, headers=None, **kwargs):
        captured_headers.append(dict(headers or {}))
        return mock_get_response

    mock_client = AsyncMock()
    mock_client.get = fake_get
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("scripts.provision_vobiz_trunk.httpx.AsyncClient", return_value=mock_client):
        await patch_vobiz_inbound_destination(
            auth_id="test_auth_id",
            auth_token="test_auth_token",
            vobiz_trunk_id="trunk_001",
            livekit_sip_uri="vachanam-agent.fly.dev",
        )

    assert len(captured_headers) == 1, "Expected exactly one GET request"
    sent = captured_headers[0]
    # Must use X-Auth-* headers
    assert sent.get("X-Auth-ID") == "test_auth_id"
    assert sent.get("X-Auth-Token") == "test_auth_token"
    # Must NOT fall back to Bearer scheme
    assert "Authorization" not in sent


@pytest.mark.asyncio
async def test_patch_vobiz_uses_x_auth_headers_on_patch():
    """Both GET and PATCH calls must use X-Auth-ID / X-Auth-Token, not Bearer.

    When inbound_destination differs, the PATCH is issued — this test
    captures the headers sent on both the GET and the PATCH request.
    """
    get_json = {"inbound_destination": "old-destination.example.com"}

    mock_get_response = MagicMock()
    mock_get_response.raise_for_status = MagicMock()
    mock_get_response.json = MagicMock(return_value=get_json)

    mock_patch_response = MagicMock()
    mock_patch_response.raise_for_status = MagicMock()

    get_headers: list[dict] = []
    patch_headers: list[dict] = []

    async def fake_get(url, headers=None, **kwargs):
        get_headers.append(dict(headers or {}))
        return mock_get_response

    async def fake_patch(url, headers=None, json=None, **kwargs):
        patch_headers.append(dict(headers or {}))
        return mock_patch_response

    mock_client = AsyncMock()
    mock_client.get = fake_get
    mock_client.patch = fake_patch
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("scripts.provision_vobiz_trunk.httpx.AsyncClient", return_value=mock_client):
        await patch_vobiz_inbound_destination(
            auth_id="test_auth_id",
            auth_token="test_auth_token",
            vobiz_trunk_id="trunk_001",
            livekit_sip_uri="vachanam-agent.fly.dev",
        )

    assert len(get_headers) == 1, "Expected exactly one GET request"
    assert len(patch_headers) == 1, "Expected exactly one PATCH request"

    for label, sent in [("GET", get_headers[0]), ("PATCH", patch_headers[0])]:
        assert sent.get("X-Auth-ID") == "test_auth_id", f"{label}: missing X-Auth-ID"
        assert sent.get("X-Auth-Token") == "test_auth_token", f"{label}: missing X-Auth-Token"
        assert "Authorization" not in sent, f"{label}: must not use Authorization: Bearer"

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
    mock_sip.list_sip_outbound_trunk = AsyncMock(return_value=list_response)
    mock_sip.create_sip_outbound_trunk = AsyncMock()

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
    mock_sip.create_sip_outbound_trunk.assert_not_called()


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

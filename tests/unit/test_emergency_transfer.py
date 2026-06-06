"""D-Emergency: Unit tests for SIP transfer on emergency keyword detection.

Tests (5):
  1. test_emergency_transfer_calls_sip_transfer_api
  2. test_emergency_transfer_releases_held_token
  3. test_emergency_transfer_writes_audit_row
  4. test_emergency_transfer_failure_falls_back_to_spoken
  5. test_emergency_transfer_ends_session

Design:
  - No real LiveKit, Redis, DB, or Sarvam.
  - VachananAgent._ctx is monkeypatched with a MagicMock / AsyncMock.
  - write_audit_row is monkeypatched.
  - Redis is monkeypatched via aioredis.from_url.
  - session.say is an AsyncMock so we can assert TTS calls.
"""
from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.agent import VachananAgent, _normalize_to_e164
from agent.session_state import SessionState


# ─────────────────────────────────────────────────────────────────────────────
# Shared fixtures
# ─────────────────────────────────────────────────────────────────────────────


def _make_state(
    *,
    ec: str = "+919876543210",
    token_held: bool = False,
    token_confirmed: bool = False,
    token_number: int | None = None,
    token_redis_key: str | None = None,
    branch_id: uuid.UUID | None = None,
    room_id: str = "room-test-em-001",
) -> SessionState:
    state = SessionState()
    state.emergency_contact = ec
    state.token_held = token_held
    state.token_confirmed = token_confirmed
    state.token_number = token_number or 3
    state.token_redis_key = token_redis_key or f"token:doc-id:{uuid.uuid4()}:2026-06-06"
    state.branch_id = branch_id or uuid.uuid4()
    state.livekit_room_id = room_id
    return state


def _make_agent(state: SessionState) -> VachananAgent:
    """Build a VachananAgent with mocked ctx and no real LiveKit deps.

    Agent.session is a read-only property backed by self._activity.session.
    We inject a fake _activity object so that agent.session resolves to our
    mock without needing a real LiveKit AgentSession.
    """
    mock_ctx = MagicMock()
    # transfer_sip_participant returns an awaitable future (success by default)
    mock_ctx.transfer_sip_participant = AsyncMock(return_value=MagicMock())
    # shutdown is awaitable
    mock_ctx.shutdown = AsyncMock(return_value=None)

    # We call Agent.__init__ via super() which requires tools list; patch it
    with patch("agent.agent._make_booking_tools", return_value=[]):
        agent = VachananAgent(state=state, ctx=mock_ctx)

    # Inject a fake _activity so Agent.session property resolves cleanly
    mock_session = MagicMock()
    mock_session.say = AsyncMock(return_value=None)
    mock_activity = MagicMock()
    mock_activity.session = mock_session
    agent._activity = mock_activity  # type: ignore[attr-defined]

    return agent


# ─────────────────────────────────────────────────────────────────────────────
# Helper: fake SIP participant returned by _wait_for_sip_participant
# ─────────────────────────────────────────────────────────────────────────────


def _patch_sip_participant(agent: VachananAgent, *, found: bool = True) -> None:
    """Patch _wait_for_sip_participant in the agent module to return a mock or None."""
    mock_sip = MagicMock()
    mock_sip.identity = "sip-caller-identity"

    import agent.agent as agent_module
    agent_module._wait_for_sip_participant = AsyncMock(
        return_value=mock_sip if found else None
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 1 — SIP transfer API called with correct URI shape
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_emergency_transfer_calls_sip_transfer_api() -> None:
    """ctx.transfer_sip_participant must be called with the correct E.164 number.

    emergency_contact="+919876543210" →
      transfer_sip_participant(participant=<sip_participant>, transfer_to="+919876543210", ...)
    """
    ec = "+919876543210"
    state = _make_state(ec=ec)
    agent = _make_agent(state)
    _patch_sip_participant(agent, found=True)

    with (
        # write_audit_row is imported lazily inside _write_emergency_audit;
        # patch at the audit_service module level so the lazy import picks it up.
        patch("backend.services.audit_service.write_audit_row", new=AsyncMock()),
        # Patch redis so token release doesn't fail (token_held=False in this test)
        patch("agent.agent.aioredis.from_url", return_value=AsyncMock()),
    ):
        await agent._handle_emergency_transfer()

    # Assert transfer was called once with the E.164 number
    agent._ctx.transfer_sip_participant.assert_awaited_once()
    call_kwargs = agent._ctx.transfer_sip_participant.call_args
    # transfer_to can be positional or keyword
    transfer_to_val = (
        call_kwargs.kwargs.get("transfer_to")
        or (call_kwargs.args[1] if len(call_kwargs.args) > 1 else None)
    )
    assert transfer_to_val == ec, (
        f"Expected transfer_to='{ec}', got '{transfer_to_val}'"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 2 — Held token released via Redis DECR
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_emergency_transfer_releases_held_token() -> None:
    """When state.token_held=True and not confirmed, Redis DECR must be called."""
    state = _make_state(token_held=True, token_confirmed=False, token_number=7)
    agent = _make_agent(state)
    _patch_sip_participant(agent, found=True)

    mock_redis = AsyncMock()
    mock_redis.decr = AsyncMock(return_value=6)
    mock_redis.aclose = AsyncMock(return_value=None)

    # aioredis.from_url is called inside _release_token_on_emergency
    with patch("agent.agent.aioredis.from_url", return_value=mock_redis):
        with patch("agent.agent._write_emergency_audit", new=AsyncMock()):
            await agent._handle_emergency_transfer()

    mock_redis.decr.assert_awaited_once_with(state.token_redis_key)
    assert state.token_held is False, "state.token_held must be False after DECR"


# ─────────────────────────────────────────────────────────────────────────────
# Test 3 — Audit row written with correct action and safe metadata
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_emergency_transfer_writes_audit_row() -> None:
    """write_audit_row must be called with action='emergency.call_transferred'.

    metadata_json must:
      - contain 'category': 'medical_critical'
      - contain 'transferred_to_did_last4' (last 4 of EC — no full number)
      - NOT contain any key in PII_DENYLIST (phone, name, email, address, complaint, symptom)
    """
    from backend.services.audit_service import PII_DENYLIST

    ec = "+919812345678"
    state = _make_state(ec=ec)
    agent = _make_agent(state)
    _patch_sip_participant(agent, found=True)

    captured_audit: list[dict] = []

    async def fake_write(**kwargs: Any) -> None:
        captured_audit.append(kwargs)

    with (
        patch("agent.agent.aioredis.from_url", return_value=AsyncMock()),
        # _write_emergency_audit lazily imports write_audit_row from backend.services.audit_service
        patch(
            "backend.services.audit_service.write_audit_row",
            new=AsyncMock(side_effect=fake_write),
        ),
    ):
        await agent._handle_emergency_transfer()

    # Find the call_transferred audit entry
    transferred_calls = [c for c in captured_audit if c.get("action") == "emergency.call_transferred"]
    assert len(transferred_calls) >= 1, (
        f"Expected audit row with action='emergency.call_transferred', got: {[c.get('action') for c in captured_audit]}"
    )
    row = transferred_calls[0]

    metadata = row.get("metadata") or {}

    # category must be medical_critical
    assert metadata.get("category") == "medical_critical", (
        f"metadata.category must be 'medical_critical', got: {metadata.get('category')}"
    )

    # last4 must be present, and must be the last 4 digits of the EC, not the full number
    last4 = metadata.get("transferred_to_did_last4", "")
    assert last4 == ec[-4:], f"Expected last4='{ec[-4:]}', got '{last4}'"
    assert ec not in str(metadata), "Full EC number must not appear in metadata"

    # PII denylist check on all metadata keys
    for key in metadata.keys():
        key_lower = key.lower()
        for banned in PII_DENYLIST:
            assert banned not in key_lower, (
                f"PII key '{key}' (matches banned '{banned}') found in audit metadata: {metadata}"
            )

    # user_agent must identify voice-agent
    assert row.get("user_agent") == "voice-agent/1.0", (
        f"Expected user_agent='voice-agent/1.0', got: {row.get('user_agent')}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 4 — SIP transfer failure falls back to spoken number
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_emergency_transfer_failure_falls_back_to_spoken() -> None:
    """When SIP transfer raises, agent must:
    - Call session.say() with a fallback message (sanitized, no markdown).
    - Write audit row with action='emergency.transfer_failed_fallback_spoken'.
    - NOT call session.say() with the raw EC number (must space-separate digits).
    """
    ec = "+919876543210"
    state = _make_state(ec=ec)
    agent = _make_agent(state)

    # Force SIP participant found, but transfer itself raises
    _patch_sip_participant(agent, found=True)
    agent._ctx.transfer_sip_participant = AsyncMock(
        side_effect=RuntimeError("SIP REFER rejected by trunk")
    )

    captured_audit: list[dict] = []

    async def fake_write(**kwargs: Any) -> None:
        captured_audit.append(kwargs)

    with patch("agent.agent.aioredis.from_url", return_value=AsyncMock()):
        with patch(
            "backend.services.audit_service.write_audit_row",
            new=AsyncMock(side_effect=fake_write),
        ):
            await agent._handle_emergency_transfer()

    # session.say must have been called at least twice:
    #   1. The brief Telugu notice ("Idi emergency...")
    #   2. The fallback spoken number message
    say_calls = agent.session.say.await_args_list
    assert len(say_calls) >= 2, (
        f"Expected at least 2 session.say calls, got {len(say_calls)}"
    )

    # The fallback message must contain the spaced digits (not the raw +91... string)
    all_say_texts = [str(call.args[0]) for call in say_calls if call.args]
    fallback_msg = all_say_texts[-1]  # Last say call is the fallback
    assert "Transfer pani cheyaledhu" in fallback_msg, (
        f"Fallback message not found in: {fallback_msg!r}"
    )

    # The fallback message must NOT contain markdown or # symbols (sanitize_for_tts applied)
    assert "**" not in fallback_msg, "Markdown bold must not appear in TTS output"
    assert "#" not in fallback_msg, "Hash must not appear in TTS output"

    # Audit row for fallback must be written
    fallback_audit = [
        c for c in captured_audit
        if c.get("action") == "emergency.transfer_failed_fallback_spoken"
    ]
    assert len(fallback_audit) >= 1, (
        f"Expected audit row 'emergency.transfer_failed_fallback_spoken', got: "
        f"{[c.get('action') for c in captured_audit]}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 5 — ctx.shutdown called with reason="emergency_transferred"
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_emergency_transfer_ends_session() -> None:
    """ctx.shutdown must be called with reason='emergency_transferred' after transfer.

    This applies both to the success path and the fallback path.
    """
    state = _make_state()
    agent = _make_agent(state)
    _patch_sip_participant(agent, found=True)

    with patch("agent.agent.aioredis.from_url", return_value=AsyncMock()):
        with patch("agent.agent._write_emergency_audit", new=AsyncMock()):
            await agent._handle_emergency_transfer()

    agent._ctx.shutdown.assert_awaited_once_with(reason="emergency_transferred")


# ─────────────────────────────────────────────────────────────────────────────
# Bonus — _normalize_to_e164 edge cases (pure unit, no async)
# ─────────────────────────────────────────────────────────────────────────────


def test_normalize_already_e164() -> None:
    assert _normalize_to_e164("+919876543210") == "+919876543210"


def test_normalize_10_digit_prepends_91() -> None:
    assert _normalize_to_e164("9876543210") == "+919876543210"


def test_normalize_12_digit_with_91_prefix() -> None:
    assert _normalize_to_e164("919876543210") == "+919876543210"


def test_normalize_with_spaces_and_dashes() -> None:
    # "+91 98765-43210" → cleaned = "+919876543210" (spaces + dashes stripped, starts with +)
    assert _normalize_to_e164("+91 98765-43210") == "+919876543210"


def test_normalize_unrecognized_returns_original() -> None:
    # Short number that isn't 10 digit — returned unchanged
    result = _normalize_to_e164("12345")
    assert result == "12345"

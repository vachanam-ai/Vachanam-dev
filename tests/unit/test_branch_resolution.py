"""Unit tests for _resolve_branch_from_sip and _wait_for_sip_participant.

Tests cover:
  1. DID found in DB → returns branch_id
  2. DID not in DB → raises ValueError
  3. No SIP participant → falls back to room metadata
  4. No SIP participant and no metadata → raises ValueError

All DB access is mocked — no running Postgres required.
"""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from agent.agent import _resolve_branch_from_sip, _wait_for_sip_participant


_FAKE_BRANCH_ID = uuid4()
_FAKE_DID = "+914066123456"
_FAKE_PHONE = "+919876543210"


def _make_fake_sip_participant(did: str = _FAKE_DID, phone: str = _FAKE_PHONE):
    """Return a fake RemoteParticipant with SIP attributes."""
    p = MagicMock()
    p.attributes = {
        "sip.trunkPhoneNumber": did,
        "sip.phoneNumber": phone,
    }
    return p


def _make_fake_ctx(metadata: dict | None = None, sip_participant=None):
    """Return a fake JobContext."""
    ctx = MagicMock()
    ctx.room.metadata = json.dumps(metadata) if metadata else None
    if sip_participant is not None:
        ctx.wait_for_participant = AsyncMock(return_value=sip_participant)
    else:
        # Simulate timeout
        async def _timeout_wait(**kwargs):
            raise asyncio.TimeoutError()
        ctx.wait_for_participant = _timeout_wait
    return ctx


class _FakeScalar:
    """Mimics SQLAlchemy scalar_one_or_none() result."""
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


@pytest.mark.asyncio
async def test_branch_resolved_from_did_when_found():
    """When SIP participant present and DID matches DB branch → returns branch_id."""
    sip = _make_fake_sip_participant()
    ctx = _make_fake_ctx(sip_participant=sip)

    mock_result = _FakeScalar(_FAKE_BRANCH_ID)

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("agent.agent.AsyncSessionLocal", return_value=mock_session_ctx):
        branch_id, patient_phone = await _resolve_branch_from_sip(ctx)

    assert branch_id == _FAKE_BRANCH_ID
    assert patient_phone == _FAKE_PHONE


@pytest.mark.asyncio
async def test_branch_not_found_for_did_raises():
    """When DID is present but no branch row matches → raises ValueError."""
    sip = _make_fake_sip_participant()
    ctx = _make_fake_ctx(sip_participant=sip)

    mock_result = _FakeScalar(None)  # DB returns no branch

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("agent.agent.AsyncSessionLocal", return_value=mock_session_ctx):
        with pytest.raises(ValueError, match="No branch configured for DID"):
            await _resolve_branch_from_sip(ctx)


@pytest.mark.asyncio
async def test_fallback_to_metadata_when_no_sip_participant():
    """When no SIP participant (timeout), falls back to room.metadata branch_id."""
    ctx = _make_fake_ctx(
        metadata={"branch_id": str(_FAKE_BRANCH_ID), "plan": "clinic"},
        sip_participant=None,  # will timeout
    )

    branch_id, patient_phone = await _resolve_branch_from_sip(ctx)

    assert branch_id == _FAKE_BRANCH_ID
    assert patient_phone is None  # no phone in metadata


@pytest.mark.asyncio
async def test_raises_when_no_sip_and_no_metadata():
    """When no SIP participant and no branch_id in metadata → raises ValueError."""
    ctx = _make_fake_ctx(
        metadata={"plan": "clinic"},  # branch_id missing
        sip_participant=None,
    )

    with pytest.raises(ValueError, match="No SIP participant"):
        await _resolve_branch_from_sip(ctx)

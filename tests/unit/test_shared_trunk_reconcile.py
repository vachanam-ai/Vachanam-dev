"""Shared trunk inventories self-heal to the database source of truth."""
from contextlib import asynccontextmanager
from types import SimpleNamespace as NS

import pytest


class _Sip:
    def __init__(self):
        self.inbound = ["+919111111111", "+919999999999"]
        self.outbound = ["+919222222222", "+919999999999"]

    async def list_inbound_trunk(self, request):
        return NS(items=[NS(numbers=self.inbound)])

    async def list_outbound_trunk(self, request):
        return NS(items=[NS(numbers=self.outbound)])

    async def update_inbound_trunk_fields(self, *, trunk_id, numbers):
        self.inbound = list(numbers)

    async def update_outbound_trunk_fields(self, *, trunk_id, numbers):
        self.outbound = list(numbers)


class _LiveKit:
    def __init__(self, sip):
        self.sip = sip

    async def aclose(self):
        return None


@pytest.mark.asyncio
async def test_reconcile_adds_missing_and_removes_stale_dids(monkeypatch):
    from livekit import api
    from backend.services import livekit_sip

    sip = _Sip()
    monkeypatch.setenv("LIVEKIT_URL", "wss://livekit.test")
    monkeypatch.setenv("LIVEKIT_API_KEY", "key")
    monkeypatch.setenv("INBOUND_TRUNK_ID", "ST_in")
    monkeypatch.setattr(livekit_sip, "_outbound_trunk_id", lambda: "ST_out")
    monkeypatch.setattr(api, "LiveKitAPI", lambda: _LiveKit(sip))

    @asynccontextmanager
    async def unlocked(_trunk_id):
        yield

    monkeypatch.setattr(livekit_sip, "_trunk_write_lock", unlocked)
    desired = ["+919111111111", "+919222222222"]
    result = await livekit_sip.reconcile_shared_trunk_numbers(desired)

    assert result["inbound"]["ok"] is True
    assert result["outbound"]["ok"] is True
    assert sip.inbound == desired
    assert sip.outbound == desired


@pytest.mark.asyncio
async def test_reconcile_fails_closed_without_provider_credentials(monkeypatch):
    from backend.services import livekit_sip

    monkeypatch.delenv("LIVEKIT_URL", raising=False)
    monkeypatch.delenv("LIVEKIT_API_KEY", raising=False)
    monkeypatch.setenv("INBOUND_TRUNK_ID", "ST_in")
    monkeypatch.setattr(livekit_sip, "_outbound_trunk_id", lambda: "ST_out")

    result = await livekit_sip.reconcile_shared_trunk_numbers(["+919111111111"])
    assert result["inbound"]["ok"] is False
    assert result["outbound"]["ok"] is False

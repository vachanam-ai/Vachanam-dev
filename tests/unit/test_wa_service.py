"""WA T3: wa_service payload shapes, gate no-ops, RULE 4 never-raise."""
import uuid
from types import SimpleNamespace

import httpx
import pytest

from backend.config import settings
from backend.services import wa_service


def _branch(linked=True):
    return SimpleNamespace(
        id=uuid.uuid4(),
        wa_phone_number_id="111222333" if linked else None,
    )


class _Resp:
    status_code = 200

    def raise_for_status(self):
        pass


def _capture_post(sent):
    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            sent.append({"url": url, "headers": headers, "json": json})
            return _Resp()

    return _Client


# ── gate ──────────────────────────────────────────────────────────────────────

def test_gate_requires_creds_link_and_plan(monkeypatch):
    monkeypatch.setattr(settings, "meta_access_token", "tok", raising=False)
    assert wa_service.wa_enabled(_branch(), "clinic") is True
    assert wa_service.wa_enabled(_branch(), "multi") is True
    assert wa_service.wa_enabled(_branch(), "solo") is False  # plan gate
    assert wa_service.wa_enabled(_branch(linked=False), "clinic") is False
    monkeypatch.setattr(settings, "meta_access_token", "", raising=False)
    assert wa_service.wa_enabled(_branch(), "clinic") is False  # no creds


# ── payload shapes ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_template_payload_with_buttons(monkeypatch):
    monkeypatch.setattr(settings, "meta_access_token", "tok", raising=False)
    sent = []
    monkeypatch.setattr(wa_service.httpx, "AsyncClient", _capture_post(sent))
    b = _branch()
    ok = await wa_service.send_template(
        b, "+919000000001", "booking_confirm", "te",
        ["Clinic", "Dr X", "14 July, 10:00", "5"],
        buttons=[{"id": "rs:t1", "title": "Reschedule"},
                 {"id": "cx:t1", "title": "Cancel"}],
        plan="clinic",
    )
    assert ok is True
    assert len(sent) == 1
    p = sent[0]["json"]
    assert sent[0]["url"].endswith("/111222333/messages")
    assert p["type"] == "template"
    assert p["template"]["name"] == "booking_confirm"
    assert p["template"]["language"]["code"] == "te"
    comps = p["template"]["components"]
    assert comps[0]["type"] == "body" and len(comps[0]["parameters"]) == 4
    assert comps[1]["sub_type"] == "quick_reply"
    assert comps[1]["parameters"][0]["payload"] == "rs:t1"
    assert comps[2]["index"] == "1"
    assert sent[0]["headers"]["Authorization"] == "Bearer tok"


@pytest.mark.asyncio
async def test_text_and_interactive_payloads(monkeypatch):
    monkeypatch.setattr(settings, "meta_access_token", "tok", raising=False)
    sent = []
    monkeypatch.setattr(wa_service.httpx, "AsyncClient", _capture_post(sent))
    b = _branch()
    assert await wa_service.send_text(b, "+919000000001", "hello", plan="clinic") is True
    assert sent[-1]["json"]["text"]["body"] == "hello"
    inter = {"type": "list", "body": {"text": "pick"}, "action": {}}
    assert await wa_service.send_interactive(b, "+919000000001", inter, plan="clinic") is True
    assert sent[-1]["json"]["interactive"]["type"] == "list"


# ── RULE 4 / RULE 8: failure never raises ─────────────────────────────────────

@pytest.mark.asyncio
async def test_network_failure_returns_false_never_raises(monkeypatch):
    monkeypatch.setattr(settings, "meta_access_token", "tok", raising=False)

    class _Boom:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            raise httpx.ConnectError("down")

    monkeypatch.setattr(wa_service.httpx, "AsyncClient", _Boom)
    ok = await wa_service.send_text(_branch(), "+919000000001", "hi", plan="clinic")
    assert ok is False

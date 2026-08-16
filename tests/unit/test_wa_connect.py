import uuid
from types import SimpleNamespace

import httpx
import pytest

from backend.config import settings
from backend.services import wa_connect
from backend.services.crypto import decrypt_secret


def FakeBranch(**overrides):
    base = dict(
        id=uuid.uuid4(), wa_status="none", wa_waba_id=None, wa_token_enc=None,
        wa_verified_name=None, wa_phone_number_id=None, wa_connected_at=None,
        wa_onboarding=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _response(status=200, payload=None):
    return httpx.Response(
        status,
        json=payload or {},
        request=httpx.Request("GET", "https://graph.facebook.com/v25.0/test"),
    )


class FakeClient:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    async def __aenter__(self): return self
    async def __aexit__(self, *_args): return False

    def _match(self, method, url):
        for key, response in self.routes.items():
            if key in url:
                self.calls.append((method, url))
                return response
        raise AssertionError(f"Unexpected Graph URL: {method} {url}")

    async def get(self, url, **_kwargs): return self._match("GET", url)
    async def post(self, url, **kwargs):
        self.calls.append(("POST_BODY", url, kwargs.get("json")))
        return self._match("POST", url)
    async def delete(self, url, **_kwargs): return self._match("DELETE", url)


def wire(monkeypatch, *, phone=None, subscribe=None, register=None, contacts=None, history=None):
    routes = {
        "oauth/access_token": _response(200, {
            "access_token": "BUSINESS_TOKEN", "expires_in": 5_184_000,
        }),
        "/123/phone_numbers": _response(200, {"data": [phone or {
            "id": "456", "verified_name": "Clinic", "status": "PENDING",
        }]}),
        "/123/subscribed_apps": subscribe or _response(200, {"success": True}),
        "/456/register": register or _response(200, {"success": True}),
        "/456/smb_app_data": contacts or _response(200, {"request_id": "sync-1"}),
        "/v25.0/456": _response(200, {"is_on_biz_app": True, "platform_type": "CLOUD_API"}),
    }
    client = FakeClient(routes)
    # The same endpoint handles contacts and history; return distinct IDs by
    # call order when a history response is supplied.
    if history is not None:
        original = client.post
        sync_calls = 0

        async def post(url, **kwargs):
            nonlocal sync_calls
            if "/smb_app_data" in url:
                sync_calls += 1
                client.calls.append(("POST_BODY", url, kwargs.get("json")))
                client.calls.append(("POST", url))
                return contacts if sync_calls == 1 and contacts is not None else history
            return await original(url, **kwargs)
        client.post = post
    monkeypatch.setattr(wa_connect.httpx, "AsyncClient", lambda **_kwargs: client)
    return client


@pytest.fixture(autouse=True)
def app_credentials(monkeypatch):
    monkeypatch.setattr(settings, "meta_app_id", "100", raising=False)
    monkeypatch.setattr(settings, "meta_app_secret", "secret", raising=False)
    monkeypatch.setattr(settings, "meta_graph_version", "v25.0", raising=False)


@pytest.mark.asyncio
async def test_cloud_api_flow_registers_with_encrypted_six_digit_pin(monkeypatch):
    branch = FakeBranch()
    client = wire(monkeypatch)
    result = await wa_connect.connect_branch(
        branch, code="AUTH_CODE_123", waba_id="123", phone_number_id="456",
        flow_event="FINISH", business_id="789",
    )
    register = next(call for call in client.calls if call[0] == "POST_BODY" and "/register" in call[1])
    pin = register[2]["pin"]
    assert len(pin) == 6 and pin.isdigit()
    assert decrypt_secret(branch.wa_onboarding["registration_pin_enc"]) == pin
    assert branch.wa_status == "connected"
    assert decrypt_secret(branch.wa_token_enc) == "BUSINESS_TOKEN"
    assert result["onboarding"]["payment_status"] == "required"
    assert result["onboarding"]["token_expires_at"]
    assert "registration_pin_enc" not in result["onboarding"]


@pytest.mark.asyncio
async def test_coexistence_skips_registration_and_starts_both_syncs(monkeypatch):
    branch = FakeBranch()
    client = wire(
        monkeypatch,
        phone={
            "id": "456", "verified_name": "Clinic", "status": "CONNECTED",
            "is_on_biz_app": True, "platform_type": "CLOUD_API",
        },
        contacts=_response(200, {"request_id": "contacts-1"}),
        history=_response(200, {"request_id": "history-1"}),
    )
    await wa_connect.connect_branch(
        branch, code="AUTH_CODE_123", waba_id="123", phone_number_id="456",
        flow_event="FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING",
    )
    assert not any("/register" in call[1] for call in client.calls)
    assert branch.wa_onboarding["mode"] == "coexistence"
    assert branch.wa_onboarding["sync"]["contacts"]["request_id"] == "contacts-1"
    assert branch.wa_onboarding["sync"]["history"]["request_id"] == "history-1"


@pytest.mark.asyncio
async def test_asset_ids_are_verified_server_side(monkeypatch):
    branch = FakeBranch()
    wire(monkeypatch, phone={"id": "999", "verified_name": "Other"})
    with pytest.raises(wa_connect.WaConnectError) as exc:
        await wa_connect.connect_branch(
            branch, code="AUTH_CODE_123", waba_id="123", phone_number_id="456",
            flow_event="FINISH",
        )
    assert exc.value.status_code == 422
    assert branch.wa_token_enc is None


@pytest.mark.asyncio
async def test_webhook_subscription_is_mandatory(monkeypatch):
    branch = FakeBranch()
    wire(monkeypatch, subscribe=_response(403, {"error": {"message": "denied"}}))
    with pytest.raises(wa_connect.WaConnectError):
        await wa_connect.connect_branch(
            branch, code="AUTH_CODE_123", waba_id="123", phone_number_id="456",
            flow_event="FINISH",
        )
    assert branch.wa_status == "none" and branch.wa_token_enc is None


@pytest.mark.asyncio
async def test_standard_registration_failure_is_not_silently_accepted(monkeypatch):
    branch = FakeBranch()
    wire(monkeypatch, register=_response(400, {"error": {"message": "bad pin"}}))
    with pytest.raises(wa_connect.WaConnectError) as exc:
        await wa_connect.connect_branch(
            branch, code="AUTH_CODE_123", waba_id="123", phone_number_id="456",
            flow_event="FINISH",
        )
    assert "register" in exc.value.detail.lower()
    assert branch.wa_status == "none"


@pytest.mark.asyncio
async def test_coexistence_sync_failure_is_visible_and_retryable(monkeypatch):
    branch = FakeBranch()
    client = wire(
        monkeypatch,
        phone={"id": "456", "status": "CONNECTED", "is_on_biz_app": True},
        contacts=_response(400, {"error": {"message": "cannot start"}}),
        history=_response(200, {"request_id": "history-1"}),
    )
    await wa_connect.connect_branch(
        branch, code="AUTH_CODE_123", waba_id="123", phone_number_id="456",
        flow_event="FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING",
    )
    assert branch.wa_status == "connected"
    assert branch.wa_onboarding["sync"]["contacts"]["status"] == "error"
    assert client.calls


@pytest.mark.asyncio
async def test_disconnect_unsubscribes_with_branch_token(monkeypatch):
    branch = FakeBranch(
        wa_waba_id="123", wa_token_enc=wa_connect.encrypt_secret("BUSINESS_TOKEN")
    )
    client = wire(monkeypatch)
    assert await wa_connect.unsubscribe_branch(branch) is True
    assert any(call[0] == "DELETE" and "/123/subscribed_apps" in call[1] for call in client.calls)


def test_unsupported_finish_event_fails_without_graph(monkeypatch):
    branch = FakeBranch()
    import asyncio
    with pytest.raises(wa_connect.WaConnectError):
        asyncio.run(wa_connect.connect_branch(
            branch, code="AUTH_CODE_123", waba_id="123", phone_number_id="456",
            flow_event="FINISH_ONLY_WABA",
        ))

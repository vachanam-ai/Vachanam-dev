"""WA MVP1 Task 9 — Embedded Signup / Tech Provider connect flow.

Pure service-level unit tests (no DB, no network — every Graph call is
mocked). Router-level auth/uniqueness/audit tests live in
test_wa_connect_router.py (needs Docker + Postgres, `db` fixture).

RULE 5: every external call retries; RULE 9: code/token never logged, and
the response payload the router returns to the browser must never carry
either. RULE 1 (WABA uniqueness) is enforced at the router layer, not here —
this module only mutates the branch object it is given.
"""
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
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class _FakeClient:
    """Routes GET/POST by URL substring to a canned httpx.Response. Order of
    `by_path` matters — first substring match wins (register before bare
    phone_number_id, since the register URL also contains that id)."""

    def __init__(self, by_path: dict):
        self._by_path = by_path
        self.calls: list[tuple] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, params=None, headers=None):
        self.calls.append(("GET", url, params, headers))
        return self._match(url)

    async def post(self, url, headers=None, json=None):
        self.calls.append(("POST", url, headers, json))
        return self._match(url)

    def _match(self, url):
        for key, resp in self._by_path.items():
            if key in url:
                return resp
        raise AssertionError(f"unexpected Graph URL in test: {url}")


def _resp(status_code: int, json_data: dict | None = None) -> httpx.Response:
    return httpx.Response(
        status_code, json=json_data or {},
        request=httpx.Request("GET", "https://graph.facebook.com/v21.0/x"),
    )


def _wire(monkeypatch, *, waba_id: str, phone_number_id: str,
          exchange=None, subscribe=None, register=None, phone_info=None):
    """Install a FakeClient covering the whole connect_branch flow. Any step
    left as None gets a benign default (200 OK) so a test only has to
    override the one step it cares about."""
    by_path = {
        "oauth/access_token": exchange or _resp(200, {"access_token": "BUSINESS_TOKEN"}),
        f"/{waba_id}/subscribed_apps": subscribe or _resp(200, {"success": True}),
        f"/{phone_number_id}/register": register or _resp(200, {"success": True}),
        f"/{phone_number_id}": phone_info or _resp(200, {"verified_name": "Sunrise Dental"}),
    }
    client = _FakeClient(by_path)
    monkeypatch.setattr(wa_connect.httpx, "AsyncClient", lambda *a, **k: client)
    return client


@pytest.fixture(autouse=True)
def _app_creds(monkeypatch):
    monkeypatch.setattr(settings, "meta_app_id", "APP123", raising=False)
    monkeypatch.setattr(settings, "meta_app_secret", "SECRET", raising=False)


# ── happy path ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_connect_branch_happy_path(monkeypatch):
    branch = FakeBranch()
    _wire(monkeypatch, waba_id="WABA1", phone_number_id="PHONE1")

    result = await wa_connect.connect_branch(
        branch, code="AUTH_CODE_XYZ", waba_id="WABA1", phone_number_id="PHONE1",
    )

    assert branch.wa_waba_id == "WABA1"
    assert branch.wa_phone_number_id == "PHONE1"
    assert branch.wa_status == "connected"
    assert branch.wa_verified_name == "Sunrise Dental"
    assert branch.wa_connected_at is not None
    assert result["registered"] is True
    assert result["verified_name"] == "Sunrise Dental"
    # The token is stored ENCRYPTED — never the plaintext Meta returned.
    assert branch.wa_token_enc != "BUSINESS_TOKEN"
    assert decrypt_secret(branch.wa_token_enc) == "BUSINESS_TOKEN"


@pytest.mark.asyncio
async def test_connect_branch_subscribes_with_the_bearer_token(monkeypatch):
    """The subscribe call must carry the token from the exchange, not the
    platform token — this is a clinic-owned WABA subscribe, not ours."""
    branch = FakeBranch()
    client = _wire(monkeypatch, waba_id="WABA2", phone_number_id="PHONE2")

    await wa_connect.connect_branch(
        branch, code="c", waba_id="WABA2", phone_number_id="PHONE2",
    )

    subscribe_calls = [c for c in client.calls if "subscribed_apps" in c[1]]
    assert len(subscribe_calls) == 1
    assert subscribe_calls[0][2]["Authorization"] == "Bearer BUSINESS_TOKEN"


@pytest.mark.asyncio
async def test_manual_connect_uses_the_pasted_token_and_never_exchanges(monkeypatch):
    """The manual path has no authorization code. It must reach the SAME
    subscribe/register/name steps with the owner's own token, and must never
    touch the oauth exchange."""
    branch = FakeBranch()
    client = _wire(monkeypatch, waba_id="WABA9", phone_number_id="PHONE9")

    result = await wa_connect.connect_branch_manual(
        branch, token="OWNER_TOKEN", waba_id="WABA9", phone_number_id="PHONE9",
    )

    assert not [c for c in client.calls if "oauth/access_token" in c[1]]
    subscribe_calls = [c for c in client.calls if "subscribed_apps" in c[1]]
    assert len(subscribe_calls) == 1
    assert subscribe_calls[0][2]["Authorization"] == "Bearer OWNER_TOKEN"
    assert branch.wa_status == "connected"
    assert decrypt_secret(branch.wa_token_enc) == "OWNER_TOKEN"
    assert result["verified_name"] == "Sunrise Dental"


@pytest.mark.asyncio
async def test_manual_connect_subscribe_failure_leaves_branch_untouched(monkeypatch):
    """The subscribe is load-bearing on BOTH paths — the shared _finish_connect
    is what stops the manual route from quietly skipping it and producing a
    branch that never receives a webhook."""
    branch = FakeBranch()
    _wire(monkeypatch, waba_id="WABA10", phone_number_id="PHONE10",
          subscribe=_resp(403, {"error": {"message": "nope"}}))

    with pytest.raises(wa_connect.WaConnectError) as e:
        await wa_connect.connect_branch_manual(
            branch, token="OWNER_TOKEN", waba_id="WABA10", phone_number_id="PHONE10",
        )

    assert e.value.status_code == 502
    assert "OWNER_TOKEN" not in e.value.detail
    assert branch.wa_waba_id is None
    assert branch.wa_status != "connected"


# ── mandatory step: subscribe failure aborts the whole connect ──────────────


@pytest.mark.asyncio
async def test_subscribe_failure_aborts_connect_and_leaves_branch_untouched(monkeypatch):
    """Subscribing to webhooks is mandatory — without it no message ever
    arrives. A failure here must raise, and must NOT leave the branch
    half-connected (no token, no waba_id, status untouched)."""
    branch = FakeBranch()
    _wire(
        monkeypatch, waba_id="WABA3", phone_number_id="PHONE3",
        subscribe=_resp(400, {"error": {"message": "bad token"}}),
    )

    with pytest.raises(wa_connect.WaConnectError) as exc:
        await wa_connect.connect_branch(
            branch, code="c", waba_id="WABA3", phone_number_id="PHONE3",
        )
    assert exc.value.status_code == 502

    # Nothing persisted — the router must never commit a half-connected branch.
    assert branch.wa_waba_id is None
    assert branch.wa_token_enc is None
    assert branch.wa_status == "none"


@pytest.mark.asyncio
async def test_token_exchange_failure_raises_and_touches_nothing(monkeypatch):
    branch = FakeBranch()
    _wire(
        monkeypatch, waba_id="WABA4", phone_number_id="PHONE4",
        exchange=_resp(400, {"error": {"message": "invalid code"}}),
    )

    with pytest.raises(wa_connect.WaConnectError) as exc:
        await wa_connect.connect_branch(
            branch, code="bad", waba_id="WABA4", phone_number_id="PHONE4",
        )
    assert exc.value.status_code == 502
    assert branch.wa_status == "none"
    assert branch.wa_token_enc is None


def test_missing_app_credentials_fails_before_any_graph_call(monkeypatch):
    """Rather than reaching Meta with an empty client_id/secret."""
    monkeypatch.setattr(settings, "meta_app_id", "", raising=False)
    monkeypatch.setattr(settings, "meta_app_secret", "", raising=False)
    import asyncio

    with pytest.raises(wa_connect.WaConnectError) as exc:
        asyncio.run(wa_connect._exchange_code("any-code"))
    assert exc.value.status_code == 500


# ── best-effort steps never block the connect ───────────────────────────────


@pytest.mark.asyncio
async def test_register_failure_does_not_block_connect(monkeypatch):
    """A coexistence number already live on the WhatsApp Business app can
    reject re-registration — that must not fail the connect, only the
    subscribe step is load-bearing."""
    branch = FakeBranch()
    _wire(
        monkeypatch, waba_id="WABA5", phone_number_id="PHONE5",
        register=_resp(400, {"error": {"message": "already registered"}}),
    )

    result = await wa_connect.connect_branch(
        branch, code="c", waba_id="WABA5", phone_number_id="PHONE5",
    )

    assert branch.wa_status == "connected"  # connect still succeeds
    assert result["registered"] is False


@pytest.mark.asyncio
async def test_verified_name_lookup_failure_does_not_block_connect(monkeypatch):
    branch = FakeBranch()
    _wire(
        monkeypatch, waba_id="WABA6", phone_number_id="PHONE6",
        phone_info=_resp(500, {"error": {"message": "boom"}}),
    )

    result = await wa_connect.connect_branch(
        branch, code="c", waba_id="WABA6", phone_number_id="PHONE6",
    )

    assert branch.wa_status == "connected"
    assert branch.wa_verified_name is None
    assert result["verified_name"] is None


# ── RULE 9: no secret ever reaches an error message ─────────────────────────


@pytest.mark.asyncio
async def test_error_detail_never_contains_the_code_or_token(monkeypatch):
    branch = FakeBranch()
    _wire(
        monkeypatch, waba_id="WABA7", phone_number_id="PHONE7",
        subscribe=_resp(400, {"error": {"message": "bad token"}}),
    )
    secret_code = "SUPER_SECRET_AUTH_CODE_998877"

    with pytest.raises(wa_connect.WaConnectError) as exc:
        await wa_connect.connect_branch(
            branch, code=secret_code, waba_id="WABA7", phone_number_id="PHONE7",
        )
    assert secret_code not in exc.value.detail
    assert "BUSINESS_TOKEN" not in exc.value.detail


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))

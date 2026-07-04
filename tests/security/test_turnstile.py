"""Cloudflare Turnstile gate on public auth endpoints (FIXLOG #261).

Env-gated: TURNSTILE_SECRET_KEY empty → feature OFF (all pass, no widget).
Set → /auth/{login,register,request-otp,forgot-password} demand a valid
X-Turnstile-Token. Cloudflare OUTAGE fails OPEN (RULE 8 — degraded bot
filtering beats a login outage); a REJECTED token fails CLOSED (403).
"""
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from backend.config import settings
from backend.services import turnstile as ts

pytestmark = pytest.mark.asyncio


def _req(headers: dict | None = None):
    return Request({
        "type": "http", "method": "POST", "path": "/auth/login",
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        "client": ("testclient", 123), "query_string": b"",
        "scheme": "http", "server": ("testserver", 80),
    })


class _FakeResp:
    def __init__(self, payload):
        self._p = payload

    def json(self):
        return self._p


class _FakeClient:
    def __init__(self, payload=None, exc=None):
        self._payload, self._exc = payload, exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, *a, **kw):
        if self._exc:
            raise self._exc
        return _FakeResp(self._payload)


async def test_feature_off_passes_without_token(monkeypatch):
    monkeypatch.setattr(settings, "turnstile_secret_key", "")
    await ts.require_turnstile(_req())  # no exception, no network


async def test_enforced_missing_token_403(monkeypatch):
    monkeypatch.setattr(settings, "turnstile_secret_key", "sec")
    with pytest.raises(HTTPException) as exc:
        await ts.require_turnstile(_req())
    assert exc.value.status_code == 403
    assert exc.value.detail == "captcha_failed"


async def test_enforced_rejected_token_403(monkeypatch):
    monkeypatch.setattr(settings, "turnstile_secret_key", "sec")
    monkeypatch.setattr(
        ts.httpx, "AsyncClient", lambda **kw: _FakeClient({"success": False})
    )
    with pytest.raises(HTTPException):
        await ts.require_turnstile(_req({"X-Turnstile-Token": "bad"}))


async def test_enforced_valid_token_passes(monkeypatch):
    monkeypatch.setattr(settings, "turnstile_secret_key", "sec")
    monkeypatch.setattr(
        ts.httpx, "AsyncClient", lambda **kw: _FakeClient({"success": True})
    )
    await ts.require_turnstile(_req({"X-Turnstile-Token": "good"}))


async def test_cloudflare_outage_fails_open(monkeypatch):
    """RULE 8: siteverify unreachable must NOT lock every clinic out."""
    monkeypatch.setattr(settings, "turnstile_secret_key", "sec")
    monkeypatch.setattr(
        ts.httpx, "AsyncClient", lambda **kw: _FakeClient(exc=OSError("down"))
    )
    await ts.require_turnstile(_req({"X-Turnstile-Token": "any"}))


async def test_cors_preflight_allows_turnstile_header(redis):
    """FIXLOG #263: X-Turnstile-Token missing from CORS allow_headers made the
    browser preflight reject EVERY gated auth call from the real frontend —
    widget said Success!, request never left the browser."""
    import httpx as _httpx

    from backend.main import app

    transport = _httpx.ASGITransport(app=app, client=("testclient", 123))
    async with _httpx.AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.options(
            "/auth/login",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type,x-turnstile-token",
            },
        )
    assert r.status_code == 200, r.text
    allowed = r.headers.get("access-control-allow-headers", "").lower()
    assert "x-turnstile-token" in allowed


async def test_login_endpoint_gated_end_to_end(monkeypatch, redis):
    """Enforced + no token → /auth/login 403 before any credential check."""
    import httpx as _httpx

    from backend.main import app

    monkeypatch.setattr(settings, "turnstile_secret_key", "sec")
    transport = _httpx.ASGITransport(app=app, client=("testclient", 123))
    async with _httpx.AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.post("/auth/login", json={"email": "a@b.c", "password": "x"})
    assert r.status_code == 403
    assert r.json()["detail"] == "captcha_failed"

"""Unit regression guards for bug-bounty round 4.

F3: OTP echo fails closed — a configured-but-failing provider must NOT leak the
    code in the API response. Echo only when no provider is configured (dev/test).
F7: JWT default expiry is the documented 8h, not the old 24h config drift.
"""
import pytest

from backend.config import Settings, settings
from backend.services import otp_service


def test_jwt_expire_default_is_8h():
    """F7: the auth contract documents an 8h hard expiry (was 24h drift)."""
    fresh = Settings()  # reads test env, which does not set JWT_EXPIRE_HOURS
    assert fresh.jwt_expire_hours == 8


def test_render_yaml_jwt_expire_matches_config_default():
    """iter1 #14: render.yaml must not re-introduce the 24h drift — the
    deployed JWT_EXPIRE_HOURS must equal the config default (8h). Guards against
    the env value silently diverging from the documented contract again.
    (render.yaml lives at repo root — Render auto-detects Blueprints only there.)"""
    import re
    from pathlib import Path

    content = Path("render.yaml").read_text(encoding="utf-8")
    m = re.search(r"JWT_EXPIRE_HOURS\s*\n\s*value:\s*\"?(\d+)\"?", content)
    assert m, "JWT_EXPIRE_HOURS not found in render.yaml"
    assert int(m.group(1)) == Settings().jwt_expire_hours == 8


def test_provider_configured_detects_keys(monkeypatch):
    monkeypatch.setattr(settings, "msg91_auth_key", "key", raising=False)
    monkeypatch.setattr(settings, "smtp_host", "", raising=False)
    monkeypatch.setattr(settings, "resend_api_key", "", raising=False)
    assert otp_service._provider_configured("sms") is True
    assert otp_service._provider_configured("email") is False
    assert otp_service._provider_configured("bogus") is False


@pytest.mark.asyncio
async def test_otp_not_echoed_when_provider_configured_but_send_fails(
    monkeypatch, redis
):
    """F3: configured provider + send failure → no code in response (fail closed)."""
    monkeypatch.setattr(settings, "msg91_auth_key", "key", raising=False)
    monkeypatch.setattr(settings, "otp_dev_echo", True, raising=False)
    monkeypatch.setattr(settings, "app_env", "development", raising=False)

    async def _fail_send(channel, dest, code):
        return False

    monkeypatch.setattr(otp_service, "_send", _fail_send)
    out = await otp_service.issue_code("sms", "+919999000111")
    assert out is None  # would have leaked the real code before the fix


@pytest.mark.asyncio
async def test_otp_echoed_when_no_provider(monkeypatch, redis):
    """Dev convenience preserved: no provider → echo so signup stays testable."""
    monkeypatch.setattr(settings, "msg91_auth_key", "", raising=False)
    monkeypatch.setattr(settings, "otp_dev_echo", True, raising=False)
    monkeypatch.setattr(settings, "app_env", "development", raising=False)

    out = await otp_service.issue_code("sms", "+919999000222")
    assert out is not None and len(out) == 6


def test_email_provider_configured_via_resend(monkeypatch):
    """Resend counts as a configured email provider (so OTP no longer dev-echoes)."""
    monkeypatch.setattr(settings, "smtp_host", "", raising=False)
    monkeypatch.setattr(settings, "resend_api_key", "", raising=False)
    assert otp_service._provider_configured("email") is False
    monkeypatch.setattr(settings, "resend_api_key", "re_test", raising=False)
    assert otp_service._provider_configured("email") is True


@pytest.mark.asyncio
async def test_send_email_uses_resend_when_keyed(monkeypatch):
    """When resend_api_key is set, _send_email POSTs to the Resend API and
    returns True on a 2xx — SMTP is not touched."""
    monkeypatch.setattr(settings, "resend_api_key", "re_test", raising=False)
    monkeypatch.setattr(settings, "resend_from", "Vachanam <noreply@vachanam.in>", raising=False)

    captured = {}

    class _Resp:
        status_code = 200
        text = "{}"

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return _Resp()

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    ok = await otp_service._send_email("user@example.com", "123456")
    assert ok is True
    assert captured["url"] == "https://api.resend.com/emails"
    assert captured["headers"]["Authorization"] == "Bearer re_test"
    assert captured["json"]["to"] == ["user@example.com"]
    assert "123456" in captured["json"]["text"]
    # the OTP subject must not leak the code
    assert "123456" not in captured["json"]["subject"]


@pytest.mark.asyncio
async def test_otp_send_throttled_per_destination(monkeypatch, redis):
    """G16: with a provider wired, a 2nd send to the same dest within 60s is throttled."""
    monkeypatch.setattr(settings, "msg91_auth_key", "key", raising=False)
    monkeypatch.setattr(settings, "app_env", "development", raising=False)

    sends = {"n": 0}

    async def _ok_send(channel, dest, code):
        sends["n"] += 1
        return True

    monkeypatch.setattr(otp_service, "_send", _ok_send)
    dest = f"+9199{__import__('uuid').uuid4().int % 10**8:08d}"
    await otp_service.issue_code("sms", dest)
    await otp_service.issue_code("sms", dest)  # within cooldown → no 2nd send
    assert sends["n"] == 1


def test_recording_hard_off_in_production():
    """No-voice-recording: production never records even if the flag is on."""
    prod = Settings(app_env="production", recording_enabled=True)
    assert prod.recording_allowed is False
    dev = Settings(app_env="development", recording_enabled=True)
    assert dev.recording_allowed is True
    off = Settings(app_env="development", recording_enabled=False)
    assert off.recording_allowed is False


def test_confirmed_at_is_timezone_aware():
    """G13: Token.confirmed_at is written tz-aware (no naive utcnow into a tz column)."""
    import inspect

    from agent.tools import booking_tools

    src = inspect.getsource(booking_tools.confirm_booking)
    assert "datetime.utcnow()" not in src
    assert "datetime.now(timezone.utc)" in src

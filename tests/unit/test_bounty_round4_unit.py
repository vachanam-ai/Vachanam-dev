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


def test_provider_configured_detects_keys(monkeypatch):
    monkeypatch.setattr(settings, "msg91_auth_key", "key", raising=False)
    monkeypatch.setattr(settings, "smtp_host", "", raising=False)
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

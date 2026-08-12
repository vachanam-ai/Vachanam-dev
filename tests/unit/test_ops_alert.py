"""An alert nobody receives is not an alert.

`admin_alert.alert_admin` writes a CRITICAL log line and an audit row, and its
docstring says real delivery is "deferred to TD". That is a forensic trail, not
a notification — nobody reads Render logs at 2am, which is when the events
worth alerting on happen. `ops_alert` adds the delivery half.

The two properties that make it safe to switch on are the ones tested here:
it deduplicates (the callers are hourly jobs), and it can never raise into a
scheduler.
"""
from __future__ import annotations

import pytest

from backend.services import ops_alert


@pytest.fixture(autouse=True)
def _configured(monkeypatch):
    monkeypatch.setattr(ops_alert.settings, "resend_api_key", "re_test_key")
    monkeypatch.setattr(ops_alert.settings, "alert_email", "hello@vachanam.in")


@pytest.fixture
def sent(monkeypatch):
    """Capture what would have gone to Resend."""
    calls: list[dict] = []

    async def _fake_guard(name, factory, **kw):
        calls.append({"breaker": name})
        return True

    monkeypatch.setattr("backend.services.resilience.guard", _fake_guard)
    return calls


@pytest.fixture
def _fresh_dedupe(monkeypatch):
    """Dedupe store that starts empty for each test."""
    seen: set[str] = set()

    async def _already(key: str) -> bool:
        if key in seen:
            return True
        seen.add(key)
        return False

    monkeypatch.setattr(ops_alert, "_already_sent", _already)
    return seen


@pytest.mark.asyncio
async def test_it_sends_the_first_time(sent, _fresh_dedupe):
    ok = await ops_alert.send_ops_alert(
        event="spend.warn", dedupe_key="k1", subject="s", body="b"
    )
    assert ok is True
    assert len(sent) == 1


@pytest.mark.asyncio
async def test_the_same_key_is_suppressed(sent, _fresh_dedupe):
    """The callers run hourly. Without this, one standing condition mails 24x/day
    and burns the Resend quota Vinay tightened on 2026-07-12."""
    for _ in range(5):
        await ops_alert.send_ops_alert(
            event="spend.warn", dedupe_key="same", subject="s", body="b"
        )
    assert len(sent) == 1


@pytest.mark.asyncio
async def test_a_different_key_still_gets_through(sent, _fresh_dedupe):
    await ops_alert.send_ops_alert(event="e", dedupe_key="a", subject="s", body="b")
    await ops_alert.send_ops_alert(event="e", dedupe_key="b", subject="s", body="b")
    assert len(sent) == 2


@pytest.mark.asyncio
async def test_unconfigured_is_quiet_and_never_raises(sent, monkeypatch, _fresh_dedupe):
    """Local/dev has no Resend key. That is normal, not an error."""
    monkeypatch.setattr(ops_alert.settings, "resend_api_key", "")
    ok = await ops_alert.send_ops_alert(
        event="e", dedupe_key="k", subject="s", body="b"
    )
    assert ok is False
    assert sent == []


@pytest.mark.asyncio
async def test_no_alert_address_configured_is_quiet(sent, monkeypatch, _fresh_dedupe):
    monkeypatch.setattr(ops_alert.settings, "alert_email", "   ")
    assert await ops_alert.send_ops_alert(
        event="e", dedupe_key="k", subject="s", body="b"
    ) is False
    assert sent == []


@pytest.mark.asyncio
async def test_a_dead_resend_returns_false_instead_of_raising(monkeypatch, _fresh_dedupe):
    """A scheduler must survive its notifier being down (RULE 8)."""
    async def _fail(name, factory, **kw):
        return False  # what guard() returns on exhaustion with fallback=False

    monkeypatch.setattr("backend.services.resilience.guard", _fail)
    assert await ops_alert.send_ops_alert(
        event="e", dedupe_key="k", subject="s", body="b"
    ) is False


@pytest.mark.asyncio
async def test_it_goes_to_the_alert_address_from_the_platform_sender(monkeypatch, _fresh_dedupe):
    """alert_email, not support_email: the support desk is a different channel."""
    captured: dict = {}

    async def _capture_guard(name, factory, **kw):
        # Run the real factory against a stubbed transport to read the payload.
        import httpx

        class _Resp:
            def raise_for_status(self):
                return None

        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, headers=None, json=None):
                captured.update({"url": url, "json": json, "headers": headers})
                return _Resp()

        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _Client())
        await factory()
        return None

    monkeypatch.setattr("backend.services.resilience.guard", _capture_guard)
    await ops_alert.send_ops_alert(
        event="spend.runaway", dedupe_key="k", subject="subj", body="body"
    )
    assert captured["json"]["to"] == ["hello@vachanam.in"]
    assert captured["json"]["from"] == ops_alert.settings.resend_from
    assert captured["json"]["subject"] == "subj"
    assert "api.resend.com" in captured["url"]


@pytest.mark.asyncio
async def test_it_rides_the_shared_resend_circuit_breaker(sent, _fresh_dedupe):
    """Same breaker as support email, so a dead Resend is visible in one place."""
    await ops_alert.send_ops_alert(event="e", dedupe_key="k", subject="s", body="b")
    assert sent[0]["breaker"] == "resend_email"


@pytest.mark.asyncio
async def test_redis_trouble_sends_rather_than_silences(monkeypatch, sent):
    """Fail LOUD: a missed alert is the failure that matters, a duplicate is not."""
    def _boom():
        raise RuntimeError("redis down")

    monkeypatch.setattr("backend.redis_client.get_redis", _boom)
    for _ in range(2):
        await ops_alert.send_ops_alert(
            event="e", dedupe_key="same-key", subject="s", body="b"
        )
    assert len(sent) == 2, "an unreachable Redis silenced the alert"


def test_the_dedupe_window_is_stated_in_hours():
    assert ops_alert.DEDUPE_TTL_SECONDS == 6 * 3600

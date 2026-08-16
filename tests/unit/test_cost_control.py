import pytest

from backend.config import settings
from backend.services.cost_control import (
    RATE_VERSION,
    billed_call_minutes,
    collect_provider_snapshots,
    measured_ai_cost_inr,
)


def test_rate_card_prices_raw_units_without_rounding_to_call_minutes(monkeypatch):
    monkeypatch.setattr(settings, "cost_usd_inr", 96.0)
    cost = measured_ai_cost_inr(
        stt_audio_seconds=3600,
        tts_audio_seconds=3600,
        llm_prompt_tokens=1_000_000,
        llm_cached_tokens=250_000,
        llm_completion_tokens=1_000_000,
    )
    assert RATE_VERSION == "2026-08-16"
    assert cost == pytest.approx(341.04)


@pytest.mark.parametrize(
    ("seconds", "minutes"),
    [(0, 0), (1, 1), (59, 1), (60, 1), (61, 2), (121, 3)],
)
def test_provider_billing_rounds_each_call(seconds, minutes):
    assert billed_call_minutes(seconds) == minutes


@pytest.mark.asyncio
async def test_missing_provider_credentials_are_visible_and_fail_open(monkeypatch):
    for name in (
        "soniox_jp_api_key",
        "upstash_email",
        "upstash_api_key",
        "upstash_database_id",
        "fly_api_token",
        "render_api_key",
        "cloudflare_api_token",
    ):
        monkeypatch.setattr(settings, name, "")
    snapshots = await collect_provider_snapshots()
    assert {item.provider for item in snapshots} == {
        "soniox", "upstash", "fly", "render", "cloudflare"
    }
    assert all(item.status == "not_connected" for item in snapshots)

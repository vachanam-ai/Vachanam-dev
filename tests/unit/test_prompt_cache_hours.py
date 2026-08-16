"""Demand-created Vertex caches exist only during clinic hours."""

import inspect
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from agent.livekit_minimal import agent as ag


IST = ZoneInfo("Asia/Kolkata")


def _at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 8, 16, hour, minute, tzinfo=IST)


def test_cache_window_is_9am_to_9pm_ist():
    assert ag._prompt_cache_ttl_seconds(_at(8, 59)) == 0
    assert ag._prompt_cache_ttl_seconds(_at(9)) == 12 * 60 * 60
    assert ag._prompt_cache_ttl_seconds(_at(12)) == 9 * 60 * 60
    assert ag._prompt_cache_ttl_seconds(_at(20, 59)) == 60
    assert ag._prompt_cache_ttl_seconds(_at(21)) == 0


def test_cache_window_converts_utc_to_ist():
    nine_am_ist = datetime(2026, 8, 16, 3, 30, tzinfo=timezone.utc)
    assert ag._prompt_cache_ttl_seconds(nine_am_ist) == 12 * 60 * 60


def test_every_cache_entry_point_checks_the_window():
    for entry_point in (
        ag._load_shared_prompt_cache,
        ag._create_prompt_cache,
        ag._cached_primary_llm,
        ag._resolve_cached_primary_llm,
    ):
        assert "_prompt_cache_ttl_seconds" in inspect.getsource(entry_point)


def test_background_warmer_never_creates_prompt_caches():
    source = inspect.getsource(ag._warm_all_clinic_prompt_caches)
    assert "_create_prompt_cache" not in source

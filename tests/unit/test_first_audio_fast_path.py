"""Regression guards for the call-start latency critical path."""

from pathlib import Path


SRC = Path("agent/livekit_minimal/agent.py").read_text(encoding="utf-8")


def test_inbound_greeting_starts_before_optional_caller_reads_finish():
    """Tenant resolution is required; personalization is not allowed to block audio."""
    start = SRC.index("_early_greeting_task = asyncio.create_task")
    reads = SRC.index("_pref_res, _gate_res, _caller_res = await asyncio.gather")
    assert start < reads


def test_returning_caller_does_not_force_live_greeting_synthesis():
    """The early opening is generic and therefore has a stable cache key."""
    block = SRC[SRC.index("# A job process already loaded this public DID"):]
    block = block[: block.index("_pref_res, _gate_res, _caller_res")]
    assert "spk_caller" not in block
    assert "_early_intro_cache_key" in block
    assert "cache_key=intro_key" in block


def test_recording_notice_isolated_before_main_intro_and_capture():
    """Only the notice is awaited; the normal intro overlaps session setup."""
    fast_path = SRC[SRC.index("elif _early_greeting_task is not None:"):]
    fast_path = fast_path[: fast_path.index("elif branch_name:")]
    assert "_notice_ok = bool(await _early_greeting_task)" in fast_path
    assert "recording_notice_completed before_capture=True" in fast_path
    assert "_early_intro_texts or []" in fast_path
    start = SRC.index("_start_task = asyncio.create_task")
    assert SRC.index("recording_notice_completed before_capture=True") < start


def test_startup_does_not_open_competing_soniox_warm_stream():
    """Connection prewarm is safe; a throwaway synthesis caused production 429s."""
    assert "def _warm_session_tts" not in SRC
    assert "_tts_warm_task" not in SRC
    early = SRC[SRC.index("# Open the persistent Soniox session socket"):]
    early = early[: early.index("# A job process already loaded this public DID")]
    assert ".prewarm()" in early
    assert ".synthesize(" not in early
    assert "async def _cache_tool_fillers" in SRC
    filler = SRC[SRC.index("async def _cache_tool_fillers"):]
    filler = filler[: filler.index("_filler_cache_task =")]
    assert filler.count("await cache_filler_clips(") == 2

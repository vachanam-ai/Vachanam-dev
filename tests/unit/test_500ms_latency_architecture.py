"""Guards for the low-latency architecture requested on 2026-07-25."""

from pathlib import Path

from agent.livekit_minimal import agent as ag


SRC = Path("agent/livekit_minimal/agent.py").read_text(encoding="utf-8")


def test_local_vad_boundary_is_at_most_60ms_with_quality_guard_retained():
    assert ag.VAD_TURN_DETECTION_S <= 0.06
    assert "min_silence_duration=VAD_TURN_DETECTION_S" in SRC
    assert "settings.soniox_manual_finalize_delay_ms" in SRC
    assert "if not still_silent()" in SRC
    assert "voice_topology worker_region=%s" in SRC
    assert "llm=vertex-asia-south1 stt=soniox-jp tts=soniox-jp" in SRC


def test_llm_and_tts_run_preemptively_together():
    assert '"preemptive_generation": {' in SRC
    assert '"enabled": True' in SRC
    assert '"preemptive_tts": True' in SRC
    assert '"max_retries": 2' in SRC


def test_soniox_short_first_sentence_is_not_merged_forward():
    tts = SRC.split("def _build_soniox_tts", 1)[1].split(
        "def _soniox_prewarm_matches", 1
    )[0]
    assert "min_sentence_len=8" in tts
    assert "stream_context_len=4" in tts
    assert "retain_format=True" in tts


def test_did_route_keys_match_formatted_and_national_numbers():
    assert ag._did_route_keys("+91 40-1234-5678") == (
        "+91 40-1234-5678",
        "914012345678",
        "4012345678",
    )


def test_prewarmed_route_starts_before_authoritative_database_query():
    start = SRC.index("early_greeting_started source=prewarmed_route")
    query = SRC.index("branches = []", start)
    assert start < query
    assert "if not outbound_number and not did_from_fallback" in SRC
    assert "early_greeting_route_mismatch" in SRC


def test_dummy_llm_warm_request_removed():
    assert "async def _prewarm_llm" not in SRC
    assert 'content="Ok"' not in SRC

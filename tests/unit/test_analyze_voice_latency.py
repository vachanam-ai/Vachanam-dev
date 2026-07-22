"""Task 1.2: the latency report script + wiring source-guards (Task 1.1).

The script consumes exported log lines, keeps only `voice_turn_latency` rows,
and reports p50/p95/p99 by cohort. Contract: `null` parses to None (never 0 —
a fake zero would hide a broken stage), and an unaccounted_ms p50 over 100ms
prints the plan's instrumentation-incomplete warning (tuning must pause).
"""
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "analyze_voice_latency", Path("scripts/analyze_voice_latency.py")
)
avl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_spec and avl)

LINE = (
    "2026-07-22 01:00:00 [info] voice_turn_latency session=ab12cd34 turn=2 "
    "kind=chat language=te cache_hit=True total_ms=1250.0 stt_finalize_ms=500.0 "
    "commit_ms=100.0 eou_delay_ms=600.0 transcription_delay_ms=500.0 "
    "llm_ttft_ms=670.0 llm_runs=1 safety_buffer_ms=50.0 tts_ttfb_ms=250.0 "
    "unaccounted_ms=-320.0"
)


def test_parse_line_extracts_fields_and_null_is_none():
    row = avl.parse_line(LINE.replace("tts_ttfb_ms=250.0", "tts_ttfb_ms=null"))
    assert row["total_ms"] == 1250.0
    assert row["tts_ttfb_ms"] is None
    assert row["turn"] == 2
    assert row["kind"] == "chat"
    assert row["cache_hit"] is True
    assert avl.parse_line("some unrelated log line") is None


def test_report_groups_cohorts_and_computes_percentiles():
    rows = []
    for total in (1000.0, 1200.0, 1400.0, 1600.0, 1800.0):
        rows.append(avl.parse_line(LINE.replace("total_ms=1250.0", f"total_ms={total}")))
    text = avl.render_report(rows)
    assert "p50" in text and "p95" in text
    assert "1400" in text  # p50 of the five totals
    assert "chat" in text


def test_unaccounted_over_100ms_p50_prints_pause_warning():
    bad = LINE.replace("unaccounted_ms=-320.0", "unaccounted_ms=400.0")
    rows = [avl.parse_line(bad)] * 3
    text = avl.render_report(rows)
    assert "instrumentation incomplete" in text.lower()


def test_turn_lines_mirrored_to_redis_durably():
    """Fly's log buffer rotates within minutes — real calls' turn lines were
    LOST before they could be read (2026-07-22, Vinay's test calls). Every
    summary line must also ride Redis (same #432 durability pattern) so the
    Phase-2 corpus survives. Best-effort: Redis failure can't touch the call."""
    src = Path("agent/livekit_minimal/agent.py").read_text(encoding="utf-8")
    emit = src.split("def _emit_turn_summary")[1][:1200]
    assert "rpush" in emit and "lat:turns" in emit
    assert "expire" in emit
    assert "except Exception" in emit  # telemetry must never touch the call
    # analyzer can read that list back
    ascript = Path("scripts/analyze_voice_latency.py").read_text(encoding="utf-8")
    assert "--redis" in ascript and "lat:turns" in ascript


def test_agent_wiring_source_guards():
    src = Path("agent/livekit_minimal/agent.py").read_text(encoding="utf-8")
    # trace created per session, emitted through the logger, flushed at shutdown
    assert "TurnLatencyTrace(" in src
    assert 'session.userdata["turn_trace"]' in src
    assert "_turn_trace.mark_speech_end()" in src
    assert "_turn_trace.mark_turn_committed(" in src
    assert "_turn_trace.mark_llm_run(" in src
    assert "_turn_trace.mark_tts(" in src
    assert "_turn_trace.flush()" in src
    # guard buffer stamps ride tts_node around the internal-speech firewall
    assert "mark_guard_first_in" in src and "mark_guard_first_out" in src
    # privacy: tool wiring passes the NAME only, never arguments
    assert 'getattr(calls[0], "name", "unknown")' in src

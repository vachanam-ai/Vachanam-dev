"""Plan 2026-07-21 Phase 1 (Task 1.1): correlated per-turn latency trace.

The trace joins the separate lat_* signals into ONE summary per caller turn so
the ~1s unattributed gap (TTFA review F1/F2) becomes measurable. Contracts
pinned here, per the plan's acceptance criteria:

  * turn_seq is per-session and monotonically increasing — never crosses
    sessions;
  * a turn's summary is flushed COMPLETE: emission waits for late-arriving
    LLM/TTS metrics (they land after playout) and fires on the NEXT turn's
    speech end, or an explicit flush();
  * missing stages are None (null in the log line), never a fake 0;
  * out-of-order / stale metrics after a flush cannot attach to the next turn;
  * llm_runs counts generations per turn — the preemptive-cancel (F2) signal;
  * the summary line carries NO transcript/phone/name/tool-args fields.
"""
import pytest

from agent.livekit_minimal.turn_trace import (
    SUMMARY_ALLOWED_KEYS,
    TurnLatencyTrace,
    format_summary_line,
)


class FakeClock:
    def __init__(self) -> None:
        self.t = 100.0

    def advance(self, s: float) -> float:
        self.t += s
        return self.t

    def __call__(self) -> float:
        return self.t


@pytest.fixture()
def trace_and_out():
    out: list[dict] = []
    clock = FakeClock()
    tr = TurnLatencyTrace("room-abc123", emit=out.append, clock=clock)
    return tr, out, clock


def _run_full_turn(tr, clock, *, ttft=0.67, ttfb=0.25):
    tr.mark_speech_end()
    clock.advance(0.5)
    tr.mark_final_transcript()
    clock.advance(0.1)
    tr.mark_turn_committed(eou_delay=0.6, transcription_delay=0.5)
    tr.mark_llm_run("sp-1", ttft=ttft)
    clock.advance(0.2)
    tr.mark_guard_first_in()
    clock.advance(0.05)
    tr.mark_guard_first_out()
    tr.mark_tts("sp-1", ttfb=ttfb)
    clock.advance(0.4)
    tr.mark_playout_start()


def test_summary_flushes_on_next_speech_end_with_all_stages(trace_and_out):
    tr, out, clock = trace_and_out
    _run_full_turn(tr, clock)
    assert out == []  # waits for late metrics — no premature emission
    tr.mark_speech_end()  # next turn starts -> previous flushes
    assert len(out) == 1
    s = out[0]
    assert s["turn"] == 1
    assert s["total_ms"] == pytest.approx(1250, abs=1)
    assert s["stt_finalize_ms"] == pytest.approx(500, abs=1)
    assert s["commit_ms"] == pytest.approx(100, abs=1)
    assert s["llm_ttft_ms"] == pytest.approx(670, abs=1)
    assert s["llm_runs"] == 1
    assert s["safety_buffer_ms"] == pytest.approx(50, abs=1)
    assert s["tts_ttfb_ms"] == pytest.approx(250, abs=1)
    assert s["unaccounted_ms"] is not None


def test_turn_seq_increments_within_session_and_never_across(trace_and_out):
    tr, out, clock = trace_and_out
    _run_full_turn(tr, clock)
    tr.mark_speech_end()
    other = TurnLatencyTrace("room-other", emit=lambda d: None, clock=clock)
    other.mark_speech_end()
    other.flush()
    _run_full_turn(tr, clock)
    tr.flush()
    assert [s["turn"] for s in out] == [1, 2]
    assert out[0]["session"] == out[1]["session"]
    # session field is a stable opaque id, not the raw room name
    assert "room-abc123" not in str(out[0]["session"])


def test_missing_stages_are_null_not_zero(trace_and_out):
    tr, out, clock = trace_and_out
    tr.mark_speech_end()
    clock.advance(1.0)
    tr.mark_playout_start()  # nothing else measured
    tr.flush()
    (s,) = out
    assert s["stt_finalize_ms"] is None
    assert s["llm_ttft_ms"] is None
    assert s["tts_ttfb_ms"] is None
    assert s["safety_buffer_ms"] is None
    assert s["total_ms"] == pytest.approx(1000, abs=1)


def test_stale_metric_after_flush_cannot_attach_to_next_turn(trace_and_out):
    tr, out, clock = trace_and_out
    _run_full_turn(tr, clock)
    tr.mark_speech_end()  # flush turn 1; turn 2 open
    tr.mark_llm_run("sp-1", ttft=9.99)  # stale speech_id from turn 1
    clock.advance(1.0)
    tr.mark_playout_start()
    tr.flush()
    assert out[1]["llm_ttft_ms"] is None  # stale metric rejected
    assert out[1]["llm_runs"] == 0


def test_llm_runs_counts_preemptive_regeneration(trace_and_out):
    tr, out, clock = trace_and_out
    tr.mark_speech_end()
    tr.mark_llm_run("sp-1", ttft=0.6)  # preemptive on interim
    tr.mark_llm_run("sp-2", ttft=0.7)  # cancelled + regenerated on final
    clock.advance(1.0)
    tr.mark_playout_start()
    tr.flush()
    (s,) = out
    assert s["llm_runs"] == 2
    assert s["llm_ttft_ms"] == pytest.approx(700, abs=1)  # the run that played


def test_tool_turn_kind_and_no_tool_args_leak(trace_and_out):
    tr, out, clock = trace_and_out
    tr.mark_speech_end()
    tr.mark_tool("check_availability", duration=1.2)
    clock.advance(2.0)
    tr.mark_playout_start()
    tr.flush()
    (s,) = out
    assert s["kind"] == "tool"
    assert s["tool"] == "check_availability"
    assert s["tool_ms"] == pytest.approx(1200, abs=1)


def test_no_emission_without_a_user_turn(trace_and_out):
    tr, out, clock = trace_and_out
    tr.mark_playout_start()  # greeting playback — no caller turn open
    tr.flush()
    assert out == []


def test_summary_carries_only_allowlisted_numeric_or_tag_fields(trace_and_out):
    """Privacy gate: transcripts, phones, names, args can never ride the line."""
    tr, out, clock = trace_and_out
    tr.set_context(language="te", provider="vertex", cache_hit=True)
    _run_full_turn(tr, clock)
    tr.flush()
    (s,) = out
    assert set(s) <= SUMMARY_ALLOWED_KEYS
    banned = {"transcript", "text", "phone", "name", "args", "caller"}
    assert not (set(s) & banned)
    line = format_summary_line(s)
    assert line.startswith("voice_turn_latency ")
    for token in line.split():
        assert "=" in token or token == "voice_turn_latency"


def test_five_scripted_turns_produce_five_coherent_lines(trace_and_out):
    tr, out, clock = trace_and_out
    for _ in range(5):
        _run_full_turn(tr, clock)
    tr.flush()
    # 4 flushed by the following turn's speech_end + 1 by flush()
    assert [s["turn"] for s in out] == [1, 2, 3, 4, 5]
    assert all(s["total_ms"] > 0 for s in out)

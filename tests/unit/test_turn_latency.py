"""Turn-gap latency (#394/#395 — clinics: "2-3s between the caller stopping
and the agent speaking is the one thing stopping them buying"). Source guards
so refactors can't silently revert:

1. Soniox endpointing tuned FROM measured evidence (transcription_delay
   0.74-0.97s at the plugin's default max_endpoint_delay_ms=2000): 800ms cap
   + endpoint_sensitivity 0.3. Turn COMMIT stays LiveKit's VAD/turn detector.
2. Thinking ack v2 (#395): v1 armed at turn commit and gated on
   current_speech — preemptive generation sets that instantly, so the ack
   NEVER played (log-proven 05:47Z). v2 is session-state driven: arms when
   the CALLER stops speaking, cancelled when anyone speaks; fires a
   pre-cached clip after 1.0s of silence.
"""
from pathlib import Path

SRC = Path("agent/livekit_minimal/agent.py").read_text(encoding="utf-8")


def test_soniox_endpointing_tuned_from_evidence():
    stt = SRC.split("def _build_stt")[1][:3500]
    assert "max_endpoint_delay_ms=800" in stt
    assert "endpoint_sensitivity=0.3" in stt
    # the tuning rationale must stay documented next to the numbers
    assert "transcription_delay" in stt


def test_thinking_ack_v2_session_state_driven():
    # armed on caller speech END (covers the transcription wait) — NOT on
    # turn commit, and NOT gated on current_speech (the v1 bug).
    ack = SRC.split("THINKING ACK v2")[1][:4000]
    assert '"listening" and ev.old_state == "speaking"' in ack
    assert '"current_speech"' not in ack  # no code gate on it (comment mention ok)
    # cancelled when the agent speaks or the caller resumes
    assert ack.count("_ack_cancel()") >= 3
    assert '"speaking":' in ack
    # fires a cached clip, invisible on failure, self-cancelling
    assert "_play_cached_filler(session)" in ack
    assert "asyncio.CancelledError" in ack
    assert "asyncio.sleep(1.0)" in ack


def test_ack_only_when_agent_not_already_speaking():
    ack = SRC.split("async def _ack_fire")[1][:800]
    assert 'agent_state", None) == "speaking"' in ack


def test_cached_filler_helper_shared_with_tool_fillers():
    # one clip mechanism — tool fillers and the thinking ack must not drift
    assert "def _play_cached_filler(sess)" in SRC
    assert "_play_cached_filler(getattr(context" in SRC


def test_soniox_finalize_on_vad_end_396():
    """#396 root cause of "it was faster before": the 07-10 Sarvam->Soniox
    switch lost flush_signal (force-final on VAD end); Soniox waited 0.6-1.8s
    for its own endpointing. The port: caller stops -> {"type":"finalize"}
    down every live Soniox socket (proven live: server answers <fin>)."""
    assert "class _FinalizingSonioxSTT(soniox.STT)" in SRC
    assert "_FinalizingSonioxSTT(" in SRC.split("def _build_stt")[1][:1500]
    fin = SRC.split("def _soniox_finalize_all")[1][:900]
    assert '\'{"type": "finalize"}\'' in fin
    # fired from the caller-stopped handler, BEFORE the ack timer arms
    handler = SRC.split("def _ack_on_user_state")[1][:900]
    assert handler.index("_soniox_finalize_all()") < handler.index("_ack_fire()")
    # weak registry: dead streams never accumulate
    assert "_weakref.WeakSet()" in SRC

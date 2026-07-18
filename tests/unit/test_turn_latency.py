"""Turn-gap latency (#394 — clinics: "2-3s between the caller stopping and
the agent speaking is the one thing stopping them buying"). Two structural
fixes, source-guarded so refactors can't silently revert them:

1. Soniox endpointing tuned FROM measured evidence (transcription_delay
   0.74-0.97s at the plugin's default max_endpoint_delay_ms=2000): 800ms cap
   + endpoint_sensitivity 0.3. Turn COMMIT stays LiveKit's VAD/turn detector.
2. Thinking ack: 0.9s after a real user turn commits with nothing speaking,
   a pre-cached filler clip plays instantly (perceived gap ~0.9s instead of
   2-3s of dead air) — cancelled when the reply beats the timer.
"""
from pathlib import Path

SRC = Path("agent/livekit_minimal/agent.py").read_text(encoding="utf-8")


def test_soniox_endpointing_tuned_from_evidence():
    stt = SRC.split("def _build_stt")[1][:3000]
    assert "max_endpoint_delay_ms=800" in stt
    assert "endpoint_sensitivity=0.3" in stt
    # the tuning rationale must stay documented next to the numbers
    assert "transcription_delay" in stt


def test_thinking_ack_armed_on_real_turns_only():
    # armed AFTER the echo guard (an echo turn must never get an ack)
    hook = SRC.split("async def on_user_turn_completed")[1]
    assert hook.index("echo_turn_discarded") < hook.index("_schedule_thinking_ack()")


def test_thinking_ack_guards():
    fn = SRC.split("def _schedule_thinking_ack")[1][:2000]
    # never stacks on speech already playing; cached clip (zero synth);
    # self-cancelling; failures invisible
    assert 'getattr(self.session, "current_speech", None) is not None' in fn
    assert "_say_lookup_filler(self)" in fn
    assert "prev.cancel()" in fn
    assert "asyncio.CancelledError" in fn
    assert "_ACK_DELAY_S = 0.9" in SRC

"""PURE-SPEED sandbox agent — raw conversation floor test (Vinay 2026-07-22).

The production pipeline minus EVERYTHING that isn't the pipeline: no DB, no
Redis, no tools, no booking, no speech firewall, no sanitizers, no greeting
machinery, no branch resolution. Same STT/LLM/TTS constructors as prod
(Soniox level-1 te → Vertex Mumbai 2.5-flash thinking-off → smallest WS
streaming), preemptive generation on, same endpointing. Receptionist persona
with the REAL Sri Venkateshwara roster baked into a tiny prompt.

Every turn prints its voice_turn_latency line straight to the terminal.

Run (local mic/speakers — measures the pipeline floor without PSTN):
    python sandbox/speed-test/speed_agent.py console

Run against LiveKit Cloud (browser mic via Agents Playground):
    python sandbox/speed-test/speed_agent.py dev

NOT for production dispatch. No AGENT_NAME registration — it can never
receive a clinic call.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from livekit.agents import (  # noqa: E402
    Agent,
    AgentSession,
    JobContext,
    WorkerOptions,
    cli,
)
from livekit.plugins import silero  # noqa: E402

from agent.i18n import get_lang  # noqa: E402
from agent.livekit_minimal.agent import (  # noqa: E402
    _build_fallback_llm,
    _build_session_tts,
    _build_stt,
)
from agent.livekit_minimal.turn_trace import (  # noqa: E402
    TurnLatencyTrace,
    format_summary_line,
)

# Real roster (read-only prod query 2026-07-22). Edit freely — sandbox only.
PROMPT = """You are the receptionist of Sri Venkateshwara clinic, Hyderabad.
Speak Telugu only, in Telugu script. Very short natural replies — one or two
spoken phrases, one question at a time, no lists, no formatting.

Doctors:
- Dr. Lakshmi — skin specialist — appointments 9:00 AM to 1:00 PM (15 min slots)
- Karishma — ENT — token queue 9:00 AM to 12:00 PM
- Dr. Srinivas — dental — appointments 9:00 AM to 11:00 PM (15 min slots)

This is a TEST line: chat freely about doctors, timings and availability,
pretend bookings succeed instantly. Never mention you are a test."""

GREETING = "నమస్కారం! శ్రీ వెంకటేశ్వర క్లినిక్. చెప్పండి, ఎలా సహాయం చేయగలను?"


async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()
    lang_cfg = get_lang("te")

    session = AgentSession(
        stt=_build_stt(lang_cfg),
        llm=_build_fallback_llm(),
        tts=_build_session_tts(lang_cfg.default_voice, lang_cfg.tts_code),
        vad=silero.VAD.load(),
        turn_detection=None,  # te unsupported by MultilingualModel (prod parity)
        preemptive_generation=True,
        min_endpointing_delay=0.05,
        max_endpointing_delay=0.3,
    )

    trace = TurnLatencyTrace(
        ctx.room.name,
        emit=lambda s: print("\n>>> " + format_summary_line(s) + "\n", flush=True),
    )
    trace.set_context(language="te")

    @session.on("user_state_changed")
    def _speech_end(ev) -> None:
        if getattr(ev, "old_state", None) == "speaking" and (
            getattr(ev, "new_state", None) == "listening"
        ):
            trace.mark_speech_end()

    @session.on("user_input_transcribed")
    def _final(ev) -> None:
        if getattr(ev, "is_final", False):
            trace.mark_final_transcript()

    @session.on("agent_state_changed")
    def _playout(ev) -> None:
        if getattr(ev, "new_state", None) == "speaking":
            trace.mark_playout_start()

    @session.on("metrics_collected")
    def _metrics(ev) -> None:
        m = ev.metrics
        tn = type(m).__name__
        if tn == "EOUMetrics":
            trace.mark_turn_committed(
                eou_delay=getattr(m, "end_of_utterance_delay", None),
                transcription_delay=getattr(m, "transcription_delay", None),
            )
        elif tn == "LLMMetrics":
            trace.mark_llm_run(
                getattr(m, "speech_id", "") or "", ttft=getattr(m, "ttft", 0.0)
            )
        elif tn == "TTSMetrics":
            trace.mark_tts(
                getattr(m, "speech_id", "") or "", ttfb=getattr(m, "ttfb", 0.0)
            )

    agent = Agent(instructions=PROMPT)
    await session.start(agent=agent, room=ctx.room)
    session.say(GREETING)


if __name__ == "__main__":
    # Dispatchable under its OWN name — the routing script points a single
    # DID's dispatch rule here for a test window; prod stays on vachanam-agent.
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, agent_name="vachanam-speed"))

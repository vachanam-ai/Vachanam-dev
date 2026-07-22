"""PURE-SPEED sandbox agent — aggressive minimal-latency build (Vinay 2026-07-22).

Prod STT/LLM/TTS constructors, NO db/tools/guards/greeting, real Sri
Venkateshwara roster. This build PUSHES every latency lever the review found
and lets Vinay hear what breaks — the sandbox is the safe place for #399-risk
settings. Every knob is an env var (change via `fly secrets set` + restart, no
rebuild):

  SPEED_OUTPUT_QUEUE_MS   default 50   LiveKit output buffer (prod hardcodes 200)
  SPEED_FINALIZE_MS       default 120  Soniox manual finalize (prod 200; <200 = #399 risk)
  SPEED_MIN_ENDPOINT_S    default 0.05
  SPEED_MAX_ENDPOINT_S    default 0.1  (prod 0.3)

Emits the full voice_turn_latency ladder per turn. Registers as vachanam-speed;
never a prod dispatch target unless route.py --speed points a DID here.
"""
from __future__ import annotations

import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from backchannel import BACKCHANNELS, pick_backchannel  # noqa: E402

import livekit.rtc as rtc  # noqa: E402

# ── LEVER 1: shrink the hardcoded LiveKit output queue ──────────────────────
# room_io/_output.py builds rtc.AudioSource(..., queue_size_ms=200) with no
# config hook. It looks the class up as `rtc.AudioSource` at call time, so
# replacing the attribute before session.start() forces a smaller buffer.
_OUTPUT_QUEUE_MS = int(os.getenv("SPEED_OUTPUT_QUEUE_MS", "50"))
_OrigAudioSource = rtc.AudioSource


class _FastAudioSource(_OrigAudioSource):
    def __init__(self, sample_rate, num_channels, *a, queue_size_ms=200, **kw):
        super().__init__(
            sample_rate, num_channels, *a,
            queue_size_ms=min(queue_size_ms, _OUTPUT_QUEUE_MS), **kw
        )


rtc.AudioSource = _FastAudioSource

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
    _SonioxFinalizeController,
    _build_fallback_llm,
    _build_session_tts,
    _build_stt,
)
from agent.livekit_minimal.turn_trace import (  # noqa: E402
    TurnLatencyTrace,
    format_summary_line,
)

_FINALIZE_MS = int(os.getenv("SPEED_FINALIZE_MS", "120"))
_MIN_ENDPOINT_S = float(os.getenv("SPEED_MIN_ENDPOINT_S", "0.05"))
_MAX_ENDPOINT_S = float(os.getenv("SPEED_MAX_ENDPOINT_S", "0.1"))

# LATENCY MASKING (Vinay 2026-07-22): play an instant ack on VAD speech-end to
# hide the ~700-1000ms STT-final wall. Picker lives in backchannel.py (pure,
# testable); the env gate lets Vinay toggle it via `fly secrets` without rebuild.
_BACKCHANNEL = os.getenv("SPEED_BACKCHANNEL", "1") != "0"

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


class _TracingAgent(Agent):
    """Plain agent + a tts_node that stamps the first synthesized frame."""

    def __init__(self, trace: TurnLatencyTrace) -> None:
        super().__init__(instructions=PROMPT)
        self._trace = trace

    async def tts_node(self, text, model_settings):
        first = True
        async for frame in super().tts_node(text, model_settings):
            if first:
                self._trace.mark_tts_first_frame()
                first = False
            yield frame


async def _prime_backchannels(tts) -> dict[str, list]:
    """Synthesize every ack ONCE at startup and keep the audio frames. Live
    synthesis costs ~300-400ms TTFB — the exact wait we're masking — so a
    filler synthesized on demand is inaudible before the real reply preempts
    it. Cached frames replay in <50ms, land the ack ~200ms after speech-end."""
    cache: dict[str, list] = {}
    for text in BACKCHANNELS:
        frames: list = []
        async for ev in tts.synthesize(text):
            frames.append(ev.frame)
        cache[text] = frames
        print(f"=== primed backchannel '{text}' frames={len(frames)} ===", flush=True)
    return cache


async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()
    lang_cfg = get_lang("te")
    finalizer = _SonioxFinalizeController(_FINALIZE_MS)
    tts = _build_session_tts(lang_cfg.default_voice, lang_cfg.tts_code)

    session = AgentSession(
        stt=_build_stt(lang_cfg, finalize_controller=finalizer),
        llm=_build_fallback_llm(),
        tts=tts,
        vad=silero.VAD.load(),
        turn_detection=None,
        preemptive_generation=True,
        min_endpointing_delay=_MIN_ENDPOINT_S,
        max_endpointing_delay=_MAX_ENDPOINT_S,
    )

    bc_cache = await _prime_backchannels(tts) if _BACKCHANNEL else {}

    trace = TurnLatencyTrace(
        ctx.room.name,
        emit=lambda s: print("\n>>> " + format_summary_line(s) + "\n", flush=True),
    )
    trace.set_context(language="te")
    _bc = {"last": None}

    @session.on("user_state_changed")
    def _state(ev) -> None:
        new = getattr(ev, "new_state", None)
        if new == "speaking":
            finalizer.cancel()
            trace.mark_speech_start()
        elif getattr(ev, "old_state", None) == "speaking" and new == "listening":
            trace.mark_speech_end()
            finalizer.schedule(
                lambda: getattr(session, "user_state", None) != "speaking"
            )
            # mask the STT-final wait: replay a pre-cached ack instantly
            if bc_cache and getattr(session, "agent_state", None) != "speaking":
                _bc["last"] = pick_backchannel(_bc["last"])
                frames = bc_cache[_bc["last"]]

                async def _replay(fs=frames):
                    for f in fs:
                        yield f

                session.say(_bc["last"], audio=_replay(), add_to_chat_ctx=False)
                print(f">>> backchannel_played text={_bc['last']}", flush=True)

    async def _on_shutdown() -> None:
        finalizer.cancel()

    ctx.add_shutdown_callback(_on_shutdown)

    @session.on("user_input_transcribed")
    def _tx(ev) -> None:
        if getattr(ev, "is_final", False):
            trace.mark_final_transcript()
        else:
            trace.mark_interim()

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
            trace.mark_llm_run(getattr(m, "speech_id", "") or "", ttft=getattr(m, "ttft", 0.0))
        elif tn == "TTSMetrics":
            trace.mark_tts(getattr(m, "speech_id", "") or "", ttfb=getattr(m, "ttfb", 0.0))

    print(
        f"\n=== SPEED PROFILE: output_queue={_OUTPUT_QUEUE_MS}ms "
        f"finalize={_FINALIZE_MS}ms endpoint={_MIN_ENDPOINT_S}/{_MAX_ENDPOINT_S}s ===\n",
        flush=True,
    )
    await session.start(agent=_TracingAgent(trace), room=ctx.room)
    session.say(GREETING)


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, agent_name="vachanam-speed"))

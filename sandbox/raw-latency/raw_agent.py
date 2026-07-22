"""RAW latency sandbox (Vinay 2026-07-22) — stt + llm + tts ONLY.

No roster, no tools, no guards, no masking, no confirmation logic. Just the
three services wired at their best-known-safe latency settings, on the real
Vobiz DID + Fly bom (production runtime). Every pipeline event from call-connect
to hangup is stamped in ms by CallTimeline and mirrored to Redis `lat:raw` so
the exact timeline survives log rotation. Purpose: see, to the millisecond,
where the turn gap actually goes.

Optimized knobs (all env-overridable via `fly secrets`, no rebuild):
  RAW_OUTPUT_QUEUE_MS  50   LiveKit output buffer (prod hardcodes 200)
  RAW_FINALIZE_MS      120  Soniox manual finalize (quality-safe floor)
  RAW_MIN_ENDPOINT_S   0.05
  RAW_MAX_ENDPOINT_S   0.1  (prod 0.3)

Registers as agent_name "vachanam-speed" so route.py --speed keeps working.
"""
from __future__ import annotations

import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import livekit.rtc as rtc  # noqa: E402

# Shrink the hardcoded 200ms LiveKit output queue (room_io looks the class up as
# rtc.AudioSource at call time, so replacing the attribute before start wins).
_OUTPUT_QUEUE_MS = int(os.getenv("RAW_OUTPUT_QUEUE_MS", "50"))
_OrigAudioSource = rtc.AudioSource


class _FastAudioSource(_OrigAudioSource):
    def __init__(self, sample_rate, num_channels, *a, queue_size_ms=200, **kw):
        super().__init__(sample_rate, num_channels, *a,
                         queue_size_ms=min(queue_size_ms, _OUTPUT_QUEUE_MS), **kw)


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
from timeline import CallTimeline, pop_sentences  # noqa: E402

_FINALIZE_MS = int(os.getenv("RAW_FINALIZE_MS", "120"))
_MIN_ENDPOINT_S = float(os.getenv("RAW_MIN_ENDPOINT_S", "0.05"))
_MAX_ENDPOINT_S = float(os.getenv("RAW_MAX_ENDPOINT_S", "0.1"))

# Minimal generic persona — a plain friendly Telugu speaker, ZERO domain, so the
# only thing under test is the pipeline. HARD length cap: the first raw call had
# the LLM emit 750 tokens / 141s of audio, which buried the streaming question.
PROMPT = (
    "నువ్వు స్నేహపూర్వకమైన వ్యక్తివి. తెలుగులో సహజంగా మాట్లాడు. "
    "గరిష్ఠంగా ఒకటి లేదా రెండు చిన్న వాక్యాలు మాత్రమే — ఎప్పుడూ 25 పదాలు దాటవద్దు. "
    "జాబితాలు, గుర్తులు వాడకు."
)
GREETING = "నమస్కారం! చెప్పండి."

# Sentence enders (Telugu danda + ASCII) — synthesize each sentence the moment
# its boundary arrives so TTS audio starts while the LLM is still generating.
_ENDERS = "।.?!…\n"


class _TLAgent(Agent):
    """Wraps each node to stamp wall-clock entry / first-output / exit."""

    def __init__(self, tl: CallTimeline) -> None:
        super().__init__(instructions=PROMPT)
        self._tl = tl

    async def stt_node(self, audio, model_settings):
        self._tl.mark("stt_node_in")
        first = True
        async for ev in super().stt_node(audio, model_settings):
            if first:
                self._tl.mark("stt_node_first_out")
                first = False
            yield ev

    async def llm_node(self, chat_ctx, tools, model_settings):
        self._tl.mark("llm_node_in")
        first = True
        async for chunk in super().llm_node(chat_ctx, tools, model_settings):
            if first:
                self._tl.mark("llm_node_first_out")
                first = False
            yield chunk
        self._tl.mark("llm_node_done")

    async def tts_node(self, text, model_settings):
        # STREAMING FIX: the smallest.ai WS plugin buffers the whole LLM output
        # before byte one. Segment the token stream into sentences here and hand
        # each complete sentence to the default node immediately — so first audio
        # lands after sentence 1, not after the entire reply.
        self._tl.mark("tts_node_in")
        state = {"first": True}

        async def _say(sentence: str):
            self._tl.mark("tts_sentence", chars=len(sentence), text=sentence)

            async def _one():
                yield sentence

            async for frame in super(_TLAgent, self).tts_node(_one(), model_settings):
                if state["first"]:
                    self._tl.mark("tts_node_first_frame")
                    state["first"] = False
                yield frame

        buf = ""
        async for tok in text:
            buf += tok
            sentences, buf = pop_sentences(buf, _ENDERS)
            for sentence in sentences:
                async for frame in _say(sentence):
                    yield frame
        if buf.strip():
            async for frame in _say(buf):
                yield frame
        self._tl.mark("tts_node_done")


async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()
    buf: list[str] = []

    def _emit(line: str) -> None:
        buf.append(line)
        print(line, flush=True)

    tl = CallTimeline(ctx.room.name, emit=_emit)
    tl.mark("connect", room=ctx.room.name[:28])

    lang = get_lang("te")
    finalizer = _SonioxFinalizeController(_FINALIZE_MS)
    session = AgentSession(
        stt=_build_stt(lang, finalize_controller=finalizer),
        llm=_build_fallback_llm(),
        tts=_build_session_tts(lang.default_voice, lang.tts_code),
        vad=silero.VAD.load(),
        turn_detection=None,
        preemptive_generation=True,
        min_endpointing_delay=_MIN_ENDPOINT_S,
        max_endpointing_delay=_MAX_ENDPOINT_S,
    )

    @session.on("user_state_changed")
    def _user(ev) -> None:
        new = getattr(ev, "new_state", None)
        if new == "speaking":
            finalizer.cancel()
        elif getattr(ev, "old_state", None) == "speaking" and new == "listening":
            finalizer.schedule(
                lambda: getattr(session, "user_state", None) != "speaking"
            )
        tl.mark(f"user_{new}")

    @session.on("agent_state_changed")
    def _agent(ev) -> None:
        tl.mark(f"agent_{getattr(ev, 'new_state', None)}")

    @session.on("user_input_transcribed")
    def _tx(ev) -> None:
        txt = getattr(ev, "transcript", "") or ""
        fin = getattr(ev, "is_final", False)
        tl.mark("stt_final" if fin else "stt_interim", chars=len(txt), text=txt)

    @session.on("metrics_collected")
    def _metrics(ev) -> None:
        m = ev.metrics
        tn = type(m).__name__
        if tn == "EOUMetrics":
            tl.mark("m_eou",
                    eou_ms=round((getattr(m, "end_of_utterance_delay", 0) or 0) * 1000, 1),
                    tx_ms=round((getattr(m, "transcription_delay", 0) or 0) * 1000, 1))
        elif tn == "STTMetrics":
            tl.mark("m_stt", audio_s=round(getattr(m, "audio_duration", 0) or 0, 2))
        elif tn == "LLMMetrics":
            tl.mark("m_llm",
                    ttft_ms=round((getattr(m, "ttft", 0) or 0) * 1000, 1),
                    dur_ms=round((getattr(m, "duration", 0) or 0) * 1000, 1),
                    toks=getattr(m, "completion_tokens", None))
        elif tn == "TTSMetrics":
            tl.mark("m_tts",
                    ttfb_ms=round((getattr(m, "ttfb", 0) or 0) * 1000, 1),
                    dur_ms=round((getattr(m, "duration", 0) or 0) * 1000, 1),
                    audio_s=round(getattr(m, "audio_duration", 0) or 0, 2))

    async def _flush() -> None:
        finalizer.cancel()
        tl.mark("disconnect")
        try:
            from backend.redis_client import get_redis
            r = await get_redis()
            if buf:
                await r.rpush("lat:raw", *buf)
                await r.ltrim("lat:raw", -6000, -1)
                await r.expire("lat:raw", 86400)
        except Exception as exc:  # never let telemetry break shutdown
            print(f"RAWLAT redis_flush_failed err={exc}", flush=True)

    ctx.add_shutdown_callback(_flush)

    print(
        f"=== RAW PROFILE: output_queue={_OUTPUT_QUEUE_MS}ms finalize={_FINALIZE_MS}ms "
        f"endpoint={_MIN_ENDPOINT_S}/{_MAX_ENDPOINT_S}s ===",
        flush=True,
    )
    await session.start(agent=_TLAgent(tl), room=ctx.room)
    tl.mark("session_started")
    session.say(GREETING)


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, agent_name="vachanam-speed"))

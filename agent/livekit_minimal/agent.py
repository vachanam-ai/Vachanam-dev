"""Vachanam LiveKit voice agent — Telugu stack, inbound + outbound via Vobiz SIP.

Stack (parity with the Pipecat baseline in agent/vobiz_minimal/ for a fair
call-quality comparison):
  STT: Sarvam Saaras v3, te-IN streaming
  LLM: Gemini 2.5 Flash (Sarvam-105b tested 2026-06-09 and rejected)
  TTS: Sarvam Bulbul v3, speaker kavitha, Telugu script input, pace 1.3

Official patterns:
  - Telephony agent:  https://docs.livekit.io/agents/start/telephony/
  - Outbound calls:   https://docs.livekit.io/agents/start/telephony/#outbound

Inbound: Vobiz forwards PSTN call -> LiveKit inbound trunk -> dispatch rule
creates room "call-..." and auto-dispatches this agent (room_config in rule).

Outbound: make_call.py creates an explicit agent dispatch with phone_number in
metadata; this agent then dials out through the Vobiz outbound trunk.
"""
import json
import logging
import os

from dotenv import load_dotenv
from livekit import agents, api
from livekit.agents import Agent, AgentSession, MetricsCollectedEvent, RoomInputOptions, metrics
from livekit.agents import llm as lk_llm
from livekit.plugins import google, noise_cancellation, openai, sarvam, silero

load_dotenv(".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vachanam-agent")

AGENT_NAME = "vachanam-agent"
OUTBOUND_TRUNK_ID = os.getenv("OUTBOUND_TRUNK_ID")

# Telugu script only — romanized Telugu gets pronounced as English phonemes.
GREETING = "నమస్కారం, ఇది వచనం డెంటల్ క్లినిక్. మీ పేరు చెప్పగలరా?"

SYSTEM_PROMPT = (
    # Role
    "మీరు వచనం డెంటల్ క్లినిక్ (హైదరాబాద్) రిసెప్షనిస్ట్. ఫోన్ కాల్‌లో పేషంట్‌కి "
    "అపాయింట్‌మెంట్ బుక్ చేస్తారు. "
    # Hard output rules — prevent meta-narration leakage
    "మీరు మాట్లాడే ప్రతి మాట పేషంట్ నేరుగా వింటారు. కాబట్టి: "
    "ఈ సూచనలను ఎప్పుడూ చదవవద్దు, వివరించవద్దు. "
    "మీరు ఏమి చేస్తున్నారో వర్ణించవద్దు (ఉదా: 'యూజర్ హలో అన్నారు కాబట్టి...' వంటివి అస్సలు అనవద్దు). "
    "రిసెప్షనిస్ట్ మాటలే తప్ప వేరే ఏ టెక్స్ట్ ఇవ్వవద్దు. "
    "లిస్ట్‌లు, మార్క్‌డౌన్, నంబరింగ్, స్పెషల్ క్యారెక్టర్‌లు వద్దు. "
    "ప్రతి రిప్లై ఒకటి లేదా రెండు చిన్న వాక్యాలే. "
    # Language
    "డిఫాల్ట్‌గా తెలుగులో, తెలుగు లిపిలో మాట్లాడండి (రోమన్ లిపి వద్దు). "
    "పేషంట్ English లేదా హిందీలో మాట్లాడితే అదే భాషలో జవాబివ్వండి. "
    # Edge cases
    "పేషంట్ మళ్ళీ మళ్ళీ హలో అంటే: 'చెప్పండి, మీ పేరు ఏమిటి?' అని మాత్రమే క్లుప్తంగా అడగండి — "
    "గ్రీటింగ్ రిపీట్ చేయవద్దు, ఎక్స్‌ప్లనేషన్ ఇవ్వవద్దు. "
    "అర్థం కాకపోతే ఒక్కసారి మళ్ళీ అడగండి. "
    # Flow
    "కాల్ మొదట్లో గ్రీటింగ్ ఇప్పటికే చెప్పబడింది. మీ పని: "
    "పేరు తెలుసుకోండి, తరువాత సమస్య అడగండి, తరువాత రేపు ఉదయం లేదా మధ్యాహ్నం "
    "స్లాట్ ఆఫర్ చేయండి, కన్ఫర్మ్ చేసి పొలైట్‌గా ముగించండి."
)


class Assistant(Agent):
    def __init__(self) -> None:
        super().__init__(instructions=SYSTEM_PROMPT)


async def entrypoint(ctx: agents.JobContext) -> None:
    await ctx.connect()
    logger.info("Joined room: %s", ctx.room.name)

    # Outbound dispatches carry the callee number in job metadata
    phone_number = None
    if ctx.job.metadata:
        try:
            phone_number = json.loads(ctx.job.metadata).get("phone_number")
        except json.JSONDecodeError:
            logger.info("Metadata is not JSON — treating as inbound call")

    # RULE 9: Gemini primary, GPT-4o-mini auto-fallback. Mandatory — the free-tier
    # Gemini key 429s after 20 req/day and also threw 503s mid-call (2026-06-10
    # outage logs); without fallback the agent goes silent mid-conversation.
    # attempt_timeout=3.0: if Gemini doesn't start streaming within 3s, fail over
    # instead of letting the caller sit in silence.
    fallback_llm = lk_llm.FallbackAdapter(
        llm=[
            google.LLM(
                api_key=os.getenv("GEMINI_API_KEY"),
                model="gemini-2.5-flash",
            ),
            openai.LLM(
                api_key=os.getenv("OPENAI_API_KEY"),
                model="gpt-4o-mini",
            ),
        ],
        attempt_timeout=3.0,
    )

    session = AgentSession(
        stt=sarvam.STT(
            api_key=os.getenv("SARVAM_API_KEY"),
            model="saaras:v3",
            language="te-IN",
            # Force the final transcript the moment client VAD detects end of
            # speech, instead of waiting on Sarvam's server-side endpointing
            # (saved ~1-2s of dead air per turn).
            flush_signal=True,
        ),
        llm=fallback_llm,
        tts=sarvam.TTS(
            api_key=os.getenv("SARVAM_API_KEY"),
            model="bulbul:v3",
            speaker="kavitha",
            target_language_code="te-IN",
            pace=1.3,
        ),
        vad=silero.VAD.load(),
        # Latency: start LLM generation on interim STT while caller is still
        # finishing the sentence; discard + regenerate if the final transcript
        # differs. Cuts perceived response delay substantially.
        preemptive_generation=True,
        # VAD-based endpointing: commit the turn sooner after silence.
        min_endpointing_delay=0.4,
        max_endpointing_delay=3.0,
    )

    # Per-turn latency telemetry (EOU delay, LLM TTFT, TTS TTFB) — drives tuning.
    @session.on("metrics_collected")
    def _on_metrics(ev: MetricsCollectedEvent) -> None:
        metrics.log_metrics(ev.metrics)

    if phone_number:
        logger.info("Outbound: dialing %s via trunk %s", phone_number, OUTBOUND_TRUNK_ID)
        try:
            await ctx.api.sip.create_sip_participant(
                api.CreateSIPParticipantRequest(
                    room_name=ctx.room.name,
                    sip_trunk_id=OUTBOUND_TRUNK_ID,
                    sip_call_to=phone_number,
                    participant_identity=f"sip_{phone_number}",
                    wait_until_answered=True,
                )
            )
            logger.info("Outbound call answered")
        except api.TwirpError as e:
            logger.error("Outbound dial failed: %s %s", e.code, e.message)
            ctx.shutdown()
            return

    await session.start(
        room=ctx.room,
        agent=Assistant(),
        room_input_options=RoomInputOptions(
            noise_cancellation=noise_cancellation.BVCTelephony(),
        ),
    )

    # Fixed greeting (skips LLM) — speaks within ~500ms, same as Pipecat baseline.
    await session.say(GREETING)


if __name__ == "__main__":
    agents.cli.run_app(
        agents.WorkerOptions(
            entrypoint_fnc=entrypoint,
            agent_name=AGENT_NAME,
        )
    )

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
from livekit.agents import Agent, AgentSession, RoomInputOptions
from livekit.plugins import google, noise_cancellation, sarvam, silero

load_dotenv(".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vachanam-agent")

AGENT_NAME = "vachanam-agent"
OUTBOUND_TRUNK_ID = os.getenv("OUTBOUND_TRUNK_ID")

# Telugu script only — romanized Telugu gets pronounced as English phonemes.
GREETING = "నమస్కారం, ఇది వచనం డెంటల్ క్లినిక్. మీ పేరు చెప్పగలరా?"

SYSTEM_PROMPT = (
    "మీరు వచనం, హైదరాబాద్‌లోని ఒక డెంటల్ క్లినిక్‌కి రిసెప్షనిస్ట్. "
    "పేషంట్‌కి అపాయింట్‌మెంట్ బుక్ చేయడంలో సహాయం చేయండి. "
    "ప్రతి రిప్లై లో ఒకటి లేదా రెండు చిన్న వాక్యాలే మాట్లాడండి. "
    "ఇది ఫోన్ కాల్ కాబట్టి లిస్ట్‌లు, మార్క్‌డౌన్, స్పెషల్ క్యారెక్టర్‌లు వాడవద్దు. "
    "తెలుగు లోనే మాట్లాడండి. English పదాలు అవసరమైతేనే వాడండి. "
    "మీ సమాధానం తెలుగు లిపిలో ఇవ్వండి, రోమన్ లిపిలో కాదు. "
    "సంభాషణ ఫ్లో: "
    "1) మొదట గ్రీటింగ్ చెప్పి పేరు అడగండి (గ్రీటింగ్ ఇప్పటికే మాట్లాడబడింది). "
    "2) పేరు తర్వాత, ఏం సమస్య అని అడగండి. "
    "3) రేపు ఉదయం లేదా మధ్యాహ్నం స్లాట్ ఆఫర్ చేయండి. "
    "4) కన్ఫర్మ్ చేసి పొలైట్‌గా కాల్ ముగించండి. "
    "గ్రీటింగ్‌ని ప్రతి టర్న్ లో రిపీట్ చేయవద్దు — మొదట ఒకసారే చెప్పండి."
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

    session = AgentSession(
        stt=sarvam.STT(
            api_key=os.getenv("SARVAM_API_KEY"),
            model="saaras:v3",
            language="te-IN",
        ),
        llm=google.LLM(
            api_key=os.getenv("GEMINI_API_KEY"),
            model="gemini-2.5-flash",
        ),
        tts=sarvam.TTS(
            api_key=os.getenv("SARVAM_API_KEY"),
            model="bulbul:v3",
            speaker="kavitha",
            target_language_code="te-IN",
            pace=1.3,
        ),
        vad=silero.VAD.load(),
    )

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

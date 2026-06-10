"""Vachanam LiveKit voice agent — handles inbound AND outbound Vobiz SIP calls.

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
from livekit.plugins import deepgram, noise_cancellation, openai, silero

load_dotenv(".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vachanam-agent")

AGENT_NAME = "vachanam-agent"
OUTBOUND_TRUNK_ID = os.getenv("OUTBOUND_TRUNK_ID")


class Assistant(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions=(
                "You are a friendly voice assistant for Vachanam on a phone call. "
                "Keep replies short and conversational — one or two sentences. "
                "Never use markdown, emojis, or special characters; plain spoken text only."
            )
        )


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
        stt=deepgram.STT(model="nova-3", language="multi"),
        llm=openai.LLM(model="gpt-4o-mini"),
        tts=openai.TTS(model="tts-1", voice="alloy"),
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

    await session.generate_reply(
        instructions="Greet the caller briefly and ask how you can help."
    )


if __name__ == "__main__":
    agents.cli.run_app(
        agents.WorkerOptions(
            entrypoint_fnc=entrypoint,
            agent_name=AGENT_NAME,
        )
    )

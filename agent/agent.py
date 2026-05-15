import asyncio
from datetime import datetime

import structlog
from livekit import agents
from livekit.agents import AgentSession, Agent, RoomInputOptions
from livekit.plugins import sarvam, google, openai as lk_openai

from agent.session_state import SessionState
from agent.services.tts_sanitizer import sanitize_for_tts
from agent.services.emergency import is_emergency
from agent.prompts.system_prompt import build_system_prompt, DoctorContext
from backend.config import settings
from backend.database import AsyncSessionLocal
from backend.models.schema import Branch, Doctor
from sqlalchemy import select, and_

logger = structlog.get_logger()

SOLO_CAP_SECONDS = 240  # 4 minutes


class VachananAgent(Agent):
    def __init__(self, state: SessionState) -> None:
        super().__init__(instructions="")  # overridden in on_enter
        self.state = state

    async def on_enter(self) -> None:
        """Fires when agent joins the room. Load clinic context and greet."""
        async with AsyncSessionLocal() as db:
            # Resolve branch from room metadata (set by Vobiz webhook)
            branch_result = await db.execute(
                select(Branch).where(Branch.id == self.state.branch_id)
            )
            branch = branch_result.scalar_one_or_none()
            if not branch:
                await self.session.say(
                    sanitize_for_tts("క్షమించండి, ఈ నంబర్ కు కనెక్ట్ కాలేదు. దయచేసి మళ్ళీ ప్రయత్నించండి.")
                )
                await self.session.disconnect()
                return

            doctor_result = await db.execute(
                select(Doctor).where(
                    and_(Doctor.branch_id == branch.id, Doctor.status == "active")
                )
            )
            doctors = doctor_result.scalars().all()

            doctor_contexts = [
                DoctorContext(
                    id=str(d.id),
                    name=d.name,
                    specialization=d.specialization or "",
                    routing_keywords=d.routing_keywords or [],
                    booking_type=d.booking_type,
                    is_default=d.is_default_doctor,
                )
                for d in doctors
            ]

            self.instructions = build_system_prompt(
                clinic_name=branch.name,
                doctors=doctor_contexts,
                emergency_contact=branch.emergency_contact or branch.whatsapp_number,
                plan=self.state.plan or "clinic",
                is_rebook=self.state.is_rebook,
            )

        greeting = sanitize_for_tts(
            f"నమస్కారం! మీరు {branch.name} కు కాల్ చేశారు. నేను మీకు అపాయింట్‌మెంట్ బుక్ చేయడంలో సహాయం చేస్తాను. మీ పేరు చెప్పగలరా?"
        )
        await self.session.say(greeting)

        logger.info("call_started", branch_id=str(self.state.branch_id), plan=self.state.plan)

    async def on_user_turn_completed(self, turn_ctx, new_message) -> None:
        """Check for emergency keywords in every user utterance."""
        if new_message and is_emergency(new_message.content):
            async with AsyncSessionLocal() as db:
                branch_result = await db.execute(
                    select(Branch).where(Branch.id == self.state.branch_id)
                )
                branch = branch_result.scalar_one_or_none()
                contact = branch.emergency_contact if branch else "the clinic"

            msg = sanitize_for_tts(
                f"నేను అర్థం చేసుకున్నాను. దయచేసి వెంటనే ఈ నంబర్ కు కాల్ చేయండి: {contact}"
            )
            await self.session.say(msg)
            # Continue booking — emergency contact given, do not disconnect

        # Solo plan 4-minute cap
        if self.state.plan == "solo":
            self.state.elapsed_seconds = int(
                (datetime.now() - self._call_start).total_seconds()
            )
            if self.state.elapsed_seconds >= SOLO_CAP_SECONDS - 10:
                await self.session.say(
                    sanitize_for_tts("మేము ముగించబోతున్నాం. మీ బుకింగ్ confirm చేస్తున్నాను.")
                )
            if self.state.elapsed_seconds >= SOLO_CAP_SECONDS:
                logger.info("solo_cap_reached", elapsed=self.state.elapsed_seconds)
                await self.session.disconnect()


async def _llm_with_fallback(messages: list) -> str:
    """Gemini 2.5 Flash primary, GPT-4o mini fallback."""
    try:
        import google.generativeai as genai
        genai.configure(api_key=settings.gemini_api_key)
        model = genai.GenerativeModel("gemini-2.5-flash")
        response = model.generate_content(messages[-1]["content"])
        return response.text
    except Exception as e:
        logger.error("gemini_failed_switching_to_openai", error=str(e))
        try:
            import openai
            client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
            resp = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                temperature=0.1,
            )
            return resp.choices[0].message.content
        except Exception as e2:
            logger.critical("both_llms_failed", error=str(e2))
            return '{"doctor_id": null, "confidence": "none"}'


async def entrypoint(ctx: agents.JobContext) -> None:
    state = SessionState()
    state.livekit_room_id = ctx.room.name

    # Parse branch_id from room metadata (set by Vobiz webhook handler)
    import json
    metadata = {}
    if ctx.room.metadata:
        try:
            metadata = json.loads(ctx.room.metadata)
        except Exception:
            pass

    from uuid import UUID
    state.branch_id = UUID(metadata.get("branch_id", "")) if metadata.get("branch_id") else None
    state.plan = metadata.get("plan", "clinic")
    state.call_type = metadata.get("call_type", "inbound_booking")
    state.is_rebook = metadata.get("is_rebook", False)
    state._call_start = datetime.now()

    await ctx.connect()

    stt = sarvam.STT(
        api_key=settings.sarvam_api_key,
        model="saaras:v3",
        language="te-IN",
    )
    tts = sarvam.TTS(
        api_key=settings.sarvam_api_key,
        model="bulbul:v3",
        language="te-IN",
    )
    llm = google.LLM(
        model="gemini-2.5-flash",
        api_key=settings.gemini_api_key,
        temperature=0.3,
    )

    session = AgentSession(stt=stt, tts=tts, llm=llm)
    agent = VachananAgent(state=state)

    @session.on("disconnected")
    async def on_disconnect():
        if state.token_held and not state.token_confirmed:
            import redis.asyncio as aioredis
            r = aioredis.from_url(settings.redis_url)
            await r.decr(state.token_redis_key)
            logger.warning(
                "token_released_on_disconnect",
                token=state.token_number,
                branch_id=str(state.branch_id),
            )

    await session.start(
        room=ctx.room,
        agent=agent,
        room_input_options=RoomInputOptions(),
    )


if __name__ == "__main__":
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint))

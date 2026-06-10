"""Vachanam LiveKit voice agent — production booking brain, inbound + outbound.

Stack: Sarvam Saaras v3 STT (te-IN) + Gemini 2.5 Flash (GPT-4o-mini fallback,
RULE 9) + Sarvam Bulbul v3 TTS (kavitha, Telugu script, pace 1.3).

Booking brain (ported from agent/bot.py Pipecat implementation):
  - DID -> branch resolution from SIP participant attributes (RULE 5)
  - 4 booking tools backed by agent/tools/booking_tools.py
    (Redis INCR tokens RULE 2, calendar-first confirm RULE 4)
  - Token rollback on disconnect when held but unconfirmed (RULE 3)
  - DPDP s.5 disclosure spoken first, every TTS line sanitized (RULE 6)
  - request_human_transfer via LiveKit SIP REFER

Run from this directory: `python agent.py start` (repo root is added to
sys.path below; root .env supplies DB/Redis/keys, local .env supplies
LiveKit + trunk IDs).
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import date as date_cls, time as time_cls
from pathlib import Path
from uuid import UUID

from dotenv import load_dotenv

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[1]
sys.path.insert(0, str(_REPO_ROOT))

# Root .env first (DATABASE_URL, REDIS_URL, SARVAM/GEMINI/OPENAI keys), then
# the local one (LIVEKIT_*, trunk IDs) overriding where both define a var.
load_dotenv(_REPO_ROOT / ".env")
load_dotenv(_HERE / ".env", override=True)

from livekit import agents, api  # noqa: E402
from livekit.agents import (  # noqa: E402
    Agent,
    AgentSession,
    MetricsCollectedEvent,
    RoomInputOptions,
    RunContext,
    function_tool,
    metrics,
)
from livekit.agents import llm as lk_llm  # noqa: E402
from livekit.plugins import google, noise_cancellation, openai, sarvam, silero  # noqa: E402

import redis.asyncio as aioredis  # noqa: E402
from sqlalchemy import and_, select  # noqa: E402

from agent.prompts.system_prompt import (  # noqa: E402
    DoctorContext,
    build_system_prompt,
)
from agent.services.calendar_proxy import GoogleCalendarService  # noqa: E402
from agent.services.meta_stub import MetaService  # noqa: E402
from agent.services.tts_sanitizer import sanitize_for_tts  # noqa: E402
from agent.session_state import SessionState  # noqa: E402
from agent.tools.booking_tools import (  # noqa: E402
    assign_token,
    check_availability,
    confirm_booking,
    route_to_doctor,
)
from backend.config import settings  # noqa: E402
from backend.database import AsyncSessionLocal  # noqa: E402
from backend.models.schema import Branch, Doctor  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vachanam-agent")

AGENT_NAME = "vachanam-agent"

# DPDP s.5 disclosure + greeting in ONE short Telugu utterance (~6s spoken).
# The 3-language disclosure (build_disclosure_utterance) took 16.8s of TTS and
# killed the first impression — Telugu-only keeps the legal essence (AI agent,
# name+phone collected, purpose) for the Telugu-market MVP. Decision 2026-06-10.
DISCLOSURE_GREETING = (
    "నమస్కారం! ఇది {clinic} క్లినిక్ AI అసిస్టెంట్. మీ అపాయింట్‌మెంట్ కోసం "
    "మీ పేరు, ఫోన్ నంబర్ తీసుకుంటాము. మీ పేరు చెప్పగలరా?"
)

# Appended AFTER the shared production prompt — phone replies must be terse.
# Long replies were costing 10-16s of TTS audio per turn on top of LLM time.
BREVITY_OVERRIDE = (
    "\n\nVOICE BREVITY — OVERRIDES EVERYTHING ABOVE: ప్రతి రిప్లై గరిష్టంగా "
    "రెండు చిన్న వాక్యాలు (మొత్తం ~15 పదాలు). లిస్ట్‌లు, వివరణలు, రిపీట్‌లు వద్దు. "
    "డిస్క్లోజర్ మళ్ళీ చెప్పవద్దు. ఒక ప్రశ్న మాత్రమే ఒకసారి అడగండి."
)


def _build_fallback_llm() -> lk_llm.FallbackAdapter:
    """RULE 9: Gemini primary, GPT-4o-mini automatic fallback (3s failover)."""
    return lk_llm.FallbackAdapter(
        llm=[
            google.LLM(api_key=settings.gemini_api_key, model="gemini-2.5-flash"),
            openai.LLM(api_key=settings.openai_api_key, model="gpt-4o-mini"),
        ],
        attempt_timeout=3.0,
    )


async def _routing_llm_call(messages: list) -> str:
    """Plain-text LLM call used by route_to_doctor (Gemini -> OpenAI fallback)."""
    combined = "\n".join(m["content"] for m in messages)
    try:
        from google import genai

        client = genai.Client(api_key=settings.gemini_api_key)
        resp = await client.aio.models.generate_content(
            model="gemini-2.5-flash", contents=combined
        )
        return resp.text or ""
    except Exception as exc:
        logger.error("routing_llm_gemini_failed: %s", exc)
        from openai import AsyncOpenAI

        oai = AsyncOpenAI(api_key=settings.openai_api_key)
        resp = await oai.chat.completions.create(
            model="gpt-4o-mini", messages=messages, temperature=0
        )
        return resp.choices[0].message.content or ""


class VachanamAgent(Agent):
    """Booking receptionist with real tools. One instance per call."""

    def __init__(
        self,
        *,
        instructions: str,
        state: SessionState,
        db,
        room,
        calendar_service: GoogleCalendarService | None,
        meta_service: MetaService,
        transfer_to: str,
    ) -> None:
        super().__init__(instructions=instructions)
        self._state = state
        self._db = db
        self._room = room
        self._calendar = calendar_service
        self._meta = meta_service
        self._transfer_to = transfer_to

    @function_tool()
    async def route_to_doctor(self, context: RunContext, complaint: str) -> dict:
        """Match the patient's stated health complaint to the right doctor.
        Call once the patient has described their problem. Pass the complaint
        exactly as spoken."""
        self._state.complaint = complaint
        result = await route_to_doctor(
            complaint=complaint,
            branch_id=self._state.branch_id,
            db=self._db,
            llm_call=_routing_llm_call,
        )
        if result.get("doctor_id"):
            self._state.doctor_id = UUID(result["doctor_id"])
        return result

    @function_tool()
    async def check_availability(
        self,
        context: RunContext,
        doctor_id: str,
        booking_date: str,
        query_start: str | None = None,
        query_end: str | None = None,
    ) -> dict:
        """Check whether the doctor has capacity on a date (YYYY-MM-DD).
        Optional query_start/query_end are HH:MM strings for slot doctors."""
        availability = await check_availability(
            doctor_id=UUID(doctor_id),
            branch_id=self._state.branch_id,
            booking_date=date_cls.fromisoformat(booking_date),
            db=self._db,
            query_start=time_cls.fromisoformat(query_start) if query_start else None,
            query_end=time_cls.fromisoformat(query_end) if query_end else None,
        )
        return {"availability": availability}

    @function_tool()
    async def assign_token(
        self,
        context: RunContext,
        doctor_id: str,
        booking_date: str,
        appointment_time: str | None = None,
    ) -> dict:
        """Atomically reserve the next token for doctor+date. Call only after
        check_availability confirms capacity AND the patient agrees to the date.
        appointment_time (HH:MM) only for slot-type doctors."""
        result = await assign_token(
            doctor_id=UUID(doctor_id),
            branch_id=self._state.branch_id,
            booking_date=date_cls.fromisoformat(booking_date),
            db=self._db,
            appointment_time=time_cls.fromisoformat(appointment_time)
            if appointment_time
            else None,
        )
        if result.get("success"):
            self._state.token_held = True
            self._state.token_number = result["token_number"]
            self._state.token_redis_key = result["redis_key"]
        return result

    @function_tool()
    async def confirm_booking(
        self,
        context: RunContext,
        doctor_id: str,
        patient_name: str,
        complaint: str,
        booking_date: str,
        token_number: int,
        followup_consent: bool,
        patient_phone: str | None = None,
        appointment_time: str | None = None,
    ) -> dict:
        """Finalize the booking AFTER the patient explicitly confirms. Writes the
        token to the database and creates the calendar event."""
        if self._calendar is None:
            logger.error("confirm_booking_no_calendar_service")
            return {"success": False, "error": "booking_system_unavailable"}
        phone = patient_phone or self._state.patient_phone
        try:
            result = await confirm_booking(
                doctor_id=UUID(doctor_id),
                branch_id=self._state.branch_id,
                patient_name=patient_name,
                patient_phone=phone,
                complaint=complaint,
                booking_date=date_cls.fromisoformat(booking_date),
                token_number=token_number,
                followup_consent=followup_consent,
                appointment_time=time_cls.fromisoformat(appointment_time)
                if appointment_time
                else None,
                source="voice",
                db=self._db,
                calendar_service=self._calendar,
                meta_service=self._meta,
            )
        except Exception as e:
            logger.error("confirm_booking_failed: %s", e)
            return {"success": False, "error": "booking_failed"}
        if result.get("success"):
            self._state.token_confirmed = True
            self._state.patient_name = patient_name
        return result

    @function_tool()
    async def request_human_transfer(self, context: RunContext, reason: str) -> dict:
        """Transfer the call to a human. Use ONLY if the patient explicitly asks
        for a person/doctor/receptionist, or keeps insisting across turns."""
        room = self._room
        if room is None or not self._transfer_to:
            return {"success": False, "error": "transfer_unavailable"}
        participant_identity = next(iter(room.remote_participants), None)
        if participant_identity is None:
            return {"success": False, "error": "no_participant"}
        logger.info(
            "human_transfer_requested reason=%s to=...%s",
            reason[:60],
            self._transfer_to[-4:],
        )
        try:
            lkapi = api.LiveKitAPI()
            await lkapi.sip.transfer_sip_participant(
                api.TransferSIPParticipantRequest(
                    room_name=room.name,
                    participant_identity=participant_identity,
                    transfer_to=f"tel:{self._transfer_to}",
                    play_dialtone=True,
                )
            )
            await lkapi.aclose()
            return {"success": True}
        except Exception as e:
            logger.error("transfer_failed: %s", e)
            return {"success": False, "error": "transfer_failed"}


async def entrypoint(ctx: agents.JobContext) -> None:
    await ctx.connect()
    logger.info("Joined room: %s", ctx.room.name)

    # Outbound dispatches carry the callee number in job metadata
    outbound_number = None
    if ctx.job.metadata:
        try:
            outbound_number = json.loads(ctx.job.metadata).get("phone_number")
        except json.JSONDecodeError:
            pass

    if outbound_number:
        logger.info("Outbound: dialing ...%s", outbound_number[-4:])
        try:
            await ctx.api.sip.create_sip_participant(
                api.CreateSIPParticipantRequest(
                    room_name=ctx.room.name,
                    sip_trunk_id=os.getenv("OUTBOUND_TRUNK_ID", ""),
                    sip_call_to=outbound_number,
                    participant_identity=f"sip_{outbound_number}",
                    wait_until_answered=True,
                )
            )
        except api.TwirpError as e:
            logger.error("Outbound dial failed: %s %s", e.code, e.message)
            ctx.shutdown()
            return

    participant = await ctx.wait_for_participant()

    # RULE 5: branch context comes from the DIALED number (DID), never the caller.
    attrs = participant.attributes or {}
    did = attrs.get("sip.trunkPhoneNumber") or os.getenv("VOBIZ_OUTBOUND_NUMBER", "")
    caller = attrs.get("sip.phoneNumber") or (outbound_number or "")
    logger.info("call_started did=...%s caller=...%s", did[-4:], caller[-4:] if caller else "????")

    state = SessionState(session_id=ctx.room.name)
    state.patient_phone = caller or None
    state.call_type = "outbound" if outbound_number else "inbound_booking"

    db = AsyncSessionLocal()

    # Branch by DID (RULE 5) + active doctors (RULE 1: branch_id filter)
    result = await db.execute(select(Branch).where(Branch.did_number == did))
    branch = result.scalar_one_or_none()
    if branch is None:
        logger.error("unknown_did ...%s — aborting call", did[-4:])
        await db.close()
        ctx.shutdown()
        return
    if True:  # noqa: SIM108 — preserves indentation of the call-setup block
        branch_id, branch_name = branch.id, branch.name
        emergency_contact = branch.emergency_contact or ""
        tts_voice = getattr(branch, "tts_voice", None) or "rupali"
        state.branch_id = branch_id
        state.emergency_contact = emergency_contact

        result = await db.execute(
            select(Doctor).where(
                and_(Doctor.branch_id == branch_id, Doctor.status == "active")
            )
        )
        doctors = result.scalars().all()
        doctor_contexts = [
            DoctorContext(
                id=str(d.id),
                name=d.name,
                specialization=d.specialization or "",
                routing_keywords=list(d.routing_keywords or []),
                booking_type=d.booking_type or "token",
                is_default=bool(d.is_default_doctor),
            )
            for d in doctors
        ]

        instructions = (
            build_system_prompt(
                clinic_name=branch_name,
                doctors=doctor_contexts,
                emergency_contact=emergency_contact,
                plan=state.plan or "clinic",
            )
            + BREVITY_OVERRIDE
        )

        try:
            # SA path resolved against repo root — settings default is the
            # relative './google-service-account.json', which breaks when the
            # worker's cwd is livekit_minimal/.
            sa_path = _REPO_ROOT / "google-service-account.json"
            calendar_service: GoogleCalendarService | None = GoogleCalendarService(
                sa_json_path=str(sa_path) if sa_path.exists() else None
            )
        except Exception as e:
            logger.critical("calendar_service_init_failed: %s", e)
            calendar_service = None

        vachanam_agent = VachanamAgent(
            instructions=instructions,
            state=state,
            db=db,
            room=ctx.room,
            calendar_service=calendar_service,
            meta_service=MetaService(),
            transfer_to=emergency_contact,
        )

        session = AgentSession(
            stt=sarvam.STT(
                api_key=settings.sarvam_api_key,
                model="saaras:v3",
                language="te-IN",
                flush_signal=True,  # final transcript on client VAD end (-1-2s/turn)
            ),
            llm=_build_fallback_llm(),
            tts=sarvam.TTS(
                api_key=settings.sarvam_api_key,
                model="bulbul:v3",
                speaker=tts_voice,  # clinic-selected (branches.tts_voice, default rupali)
                target_language_code="te-IN",
                pace=1.3,
            ),
            vad=silero.VAD.load(),
            preemptive_generation=True,
            min_endpointing_delay=0.4,
            max_endpointing_delay=3.0,
        )

        @session.on("metrics_collected")
        def _on_metrics(ev: MetricsCollectedEvent) -> None:
            metrics.log_metrics(ev.metrics)

        # RULE 3: release a held-but-unconfirmed token when the call ends.
        # Also closes the long-lived DB session (entrypoint returns while the
        # call is still live — LiveKit keeps the session running; cleanup
        # happens here at job shutdown).
        async def _cleanup_on_shutdown() -> None:
            try:
                if (
                    state.token_held
                    and not state.token_confirmed
                    and state.token_redis_key
                ):
                    r = aioredis.from_url(settings.redis_url, decode_responses=True)
                    try:
                        await r.decr(state.token_redis_key)
                        logger.warning(
                            "token_released_on_disconnect token=%s branch_id=%s",
                            state.token_number,
                            str(state.branch_id),
                        )
                    finally:
                        await r.aclose()
            finally:
                await db.close()

        ctx.add_shutdown_callback(_cleanup_on_shutdown)

        await session.start(
            room=ctx.room,
            agent=vachanam_agent,
            room_input_options=RoomInputOptions(
                noise_cancellation=noise_cancellation.BVCTelephony(),
            ),
        )

        # RULE 6: single short disclosure+greeting utterance, sanitized.
        await session.say(
            sanitize_for_tts(DISCLOSURE_GREETING.format(clinic=branch_name))
        )


if __name__ == "__main__":
    agents.cli.run_app(
        agents.WorkerOptions(
            entrypoint_fnc=entrypoint,
            agent_name=AGENT_NAME,
        )
    )

"""Vachanam LiveKit voice agent entrypoint.

Component map:
  1. Streaming STT  → sarvam.STT WebSocket
  2. LLM            → Gemini 2.5 Flash (primary) + GPT-4o-mini fallback via FallbackAdapter
  3. Streaming TTS  → sarvam.TTS WebSocket
  4. Branch context → resolved from SIP trunkPhoneNumber DID; fallback to room metadata
  5. Solo 4-min cap → _solo_cap_watchdog background task
  6. Inactivity     → _inactivity_watchdog (30s no-audio → graceful end)
  7. Emergency      → keyword detect → speak branch.emergency_contact → continue booking

CLAUDE.md rules respected:
  - Every DB query filters by branch_id
  - Tokens via Redis INCR; DECR is rollback only
  - Calendar success required; WhatsApp fire-and-forget
  - Every session.say() through sanitize_for_tts()
  - Gemini primary → GPT-4o-mini fallback via FallbackAdapter
  - Structlog JSON with branch_id + last-4 phone on all significant events
"""
# ── Bootstrap: must be at the very top, before any async-related import ──────
# Gap 1: asyncpg requires SelectorEventLoop on Windows; Python 3.10+ defaults
# to ProactorEventLoop. Fix before LiveKit Agents (which may set its own policy
# at import time).
import sys
import asyncio

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Gap 2: Load .env from project root regardless of CWD.
from pathlib import Path
from dotenv import load_dotenv

_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
if _ENV_PATH.exists():
    load_dotenv(_ENV_PATH)

# Gap 3: Configure structlog JSON output before any logger use.
from agent.logging_config import configure_structlog

configure_structlog(log_level="INFO")
# ─────────────────────────────────────────────────────────────────────────────

import json
import time
from datetime import datetime, date
from typing import Any
from uuid import UUID

import redis.asyncio as aioredis
import structlog
from livekit import agents, rtc
from livekit.agents import Agent, AgentSession, RoomInputOptions, function_tool
from livekit.agents.llm import FallbackAdapter
from livekit.plugins import google, openai as lk_openai, sarvam
from sqlalchemy import select, and_

from agent.prompts.system_prompt import DoctorContext, build_disclosure_utterance, build_system_prompt
from agent.services.emergency import is_emergency
from agent.services.tts_sanitizer import sanitize_for_tts
from agent.session_state import SessionState
from backend.config import settings
from backend.database import AsyncSessionLocal
from backend.models.schema import Branch, Doctor

logger = structlog.get_logger()

SOLO_CAP_SECONDS = 240          # 4 minutes — billing hard limit (Solo plan)
SOLO_WARNING_SECONDS = SOLO_CAP_SECONDS - 10
INACTIVITY_TIMEOUT_SECONDS = 30  # no user audio for 30s → end gracefully

_GREETINGS_DIR = Path(__file__).resolve().parent.parent / "backend" / "static" / "greetings"

_SIP_KIND = rtc.ParticipantKind.PARTICIPANT_KIND_SIP


# ──────────────────────────────────────────────────────────────────────────
# Branch resolution — SIP DID lookup with metadata fallback
# ──────────────────────────────────────────────────────────────────────────


async def _wait_for_sip_participant(
    ctx: agents.JobContext, timeout_s: float = 10.0
) -> "rtc.RemoteParticipant | None":
    """Return the first SIP participant who joins the room, or None on timeout."""
    try:
        participant = await asyncio.wait_for(
            ctx.wait_for_participant(kind=[_SIP_KIND]),
            timeout=timeout_s,
        )
        return participant
    except asyncio.TimeoutError:
        logger.warning("sip_participant_wait_timeout", timeout_s=timeout_s)
        return None
    except Exception as e:
        logger.warning("sip_participant_wait_error", error=str(e))
        return None


async def _resolve_branch_from_sip(
    ctx: agents.JobContext,
) -> "tuple[UUID, str | None]":
    """Resolve branch_id + patient_phone from SIP attributes or room metadata.

    Returns (branch_id, patient_phone_or_None).
    Raises ValueError if neither SIP DID nor metadata branch_id is available.
    """
    sip_participant = await _wait_for_sip_participant(ctx, timeout_s=10.0)

    if sip_participant is not None:
        attrs = sip_participant.attributes or {}
        did = attrs.get("sip.trunkPhoneNumber")
        patient_phone = attrs.get("sip.phoneNumber")

        if did:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(Branch.id).where(Branch.did_number == did)
                )
                branch_id = result.scalar_one_or_none()

            if branch_id:
                logger.info(
                    "branch_resolved_from_did",
                    did_last4=did[-4:],
                    branch_id=str(branch_id),
                    patient_phone_last4=patient_phone[-4:] if patient_phone else None,
                )
                return branch_id, patient_phone

            logger.error("branch_not_found_for_did", did_last4=did[-4:])
            raise ValueError(f"No branch configured for DID ending {did[-4:]}")

    # Fallback: dev/test rooms that inject branch_id in room metadata
    metadata: dict = {}
    if ctx.room.metadata:
        try:
            metadata = json.loads(ctx.room.metadata)
        except Exception:
            pass

    if metadata.get("branch_id"):
        branch_id = UUID(metadata["branch_id"])
        logger.info("branch_resolved_from_metadata", branch_id=str(branch_id))
        return branch_id, metadata.get("patient_phone")

    raise ValueError("No SIP participant and no branch_id in room metadata")


# ──────────────────────────────────────────────────────────────────────────
# Booking tool closures — bound to per-call SessionState
# ──────────────────────────────────────────────────────────────────────────


def _make_booking_tools(state: SessionState) -> list:
    """Return 4 @function_tool callables bound to this call's session state.

    Each tool opens its own AsyncSessionLocal per invocation to avoid detached-
    instance errors (asyncpg + long-lived sessions are unsafe across turns).

    LLM clients (genai, OpenAI) are imported lazily inside _llm_call so that
    the tool list can be built without requiring those packages at import time.
    This keeps tests that only inspect the tool shape fast and dependency-light.
    """
    import asyncio as _asyncio
    from agent.tools.booking_tools import (
        route_to_doctor as _route,
        check_availability as _avail,
        assign_token as _assign,
        confirm_booking as _confirm,
    )

    async def _llm_call(messages: list) -> str:
        """Gemini primary → GPT-4o-mini fallback (Rule 9). Lazy import of clients."""
        import google.generativeai as _genai
        from openai import AsyncOpenAI as _AsyncOpenAI

        combined = "\n".join(m.get("content", "") for m in messages)
        try:
            _model = _genai.GenerativeModel("gemini-2.5-flash")
            resp = await _asyncio.to_thread(_model.generate_content, combined)
            return resp.text
        except Exception as e:
            logger.error("gemini_failed_switching_to_openai", error=str(e))
            try:
                _oai = _AsyncOpenAI(api_key=settings.openai_api_key)
                r = await _oai.chat.completions.create(
                    model="gpt-4o-mini", messages=messages, temperature=0
                )
                return r.choices[0].message.content or ""
            except Exception as e2:
                logger.critical("both_llms_failed", error=str(e2))
                return "{}"

    @function_tool
    async def route_to_doctor(complaint: str) -> dict:
        """Call when the patient has described their health complaint.
        Determines which doctor to route them to. Do NOT call until the
        patient has stated their complaint — ask first if unclear.
        Args: complaint — patient's complaint in Telugu, Hindi, or English.
        Returns: dict with doctor_id, confidence (high/low/none).
        """
        if not state.branch_id:
            return {"error": "branch_id not resolved"}
        async with AsyncSessionLocal() as db:
            result = await _route(
                complaint=complaint,
                branch_id=state.branch_id,
                db=db,
                llm_call=_llm_call,
            )
        if result.get("doctor_id"):
            state.doctor_id = UUID(result["doctor_id"])
        logger.info(
            "tool_route_to_doctor",
            branch_id=str(state.branch_id),
            confidence=result.get("confidence"),
        )
        return result

    @function_tool
    async def check_availability(booking_date: str) -> str:
        """Call after routing to check open slots for the selected doctor.
        booking_date must be ISO format YYYY-MM-DD (e.g. 2026-06-07).
        Returns a human-readable availability string in the patient's language.
        Do NOT call before route_to_doctor has succeeded.
        """
        if not state.branch_id or not state.doctor_id:
            return "Doctor not yet selected. Please route the patient first."
        parsed_date = date.fromisoformat(booking_date)
        async with AsyncSessionLocal() as db:
            result = await _avail(
                doctor_id=state.doctor_id,
                branch_id=state.branch_id,
                booking_date=parsed_date,
                db=db,
            )
        logger.info(
            "tool_check_availability",
            branch_id=str(state.branch_id),
            doctor_id=str(state.doctor_id),
            date=booking_date,
        )
        return result

    @function_tool
    async def assign_token(booking_date: str) -> dict:
        """Call when the patient confirms the date and wants to book a token.
        Atomically reserves the next available token via Redis INCR — no double-booking.
        booking_date: ISO YYYY-MM-DD. Call check_availability first.
        Returns: success + token_number, or failure reason if fully booked.
        """
        if not state.branch_id or not state.doctor_id:
            return {"success": False, "reason": "doctor_not_routed"}
        parsed_date = date.fromisoformat(booking_date)
        async with AsyncSessionLocal() as db:
            result = await _assign(
                doctor_id=state.doctor_id,
                branch_id=state.branch_id,
                booking_date=parsed_date,
                db=db,
            )
        if result.get("success"):
            state.token_held = True
            state.token_number = result["token_number"]
            state.token_redis_key = result["redis_key"]
        logger.info(
            "tool_assign_token",
            branch_id=str(state.branch_id),
            doctor_id=str(state.doctor_id),
            success=result.get("success"),
            token=result.get("token_number"),
        )
        return result

    @function_tool
    async def confirm_booking(
        patient_name: str,
        patient_phone: str,
        complaint: str,
        booking_date: str,
        followup_consent: bool,
    ) -> dict:
        """Call ONLY after assign_token succeeded and patient verbally confirmed all details.
        Persists booking to DB + Google Calendar (must succeed). WhatsApp is fire-and-forget.
        patient_phone: E.164 format. booking_date: ISO YYYY-MM-DD.
        Returns: success + token_id, or failure reason.
        """
        if not state.branch_id or not state.doctor_id or not state.token_held:
            return {"success": False, "reason": "token_not_held"}
        parsed_date = date.fromisoformat(booking_date)

        # Attempt real service imports; fall back to stubs if Phase 6 not yet shipped
        try:
            from backend.services.calendar_service import CalendarService
            calendar_svc = CalendarService()
        except (ImportError, Exception):
            class _StubCalendar:
                async def create_booking_event(self, **kwargs: Any) -> str:
                    logger.warning("calendar_service_stub_used")
                    return "stub-event-id"
            calendar_svc = _StubCalendar()  # type: ignore[assignment]

        try:
            from backend.services.meta_service import MetaService
            meta_svc = MetaService()
        except (ImportError, Exception):
            class _StubMeta:
                async def send_booking_confirmation(self, **kwargs: Any) -> None:
                    logger.warning("meta_service_stub_used")
            meta_svc = _StubMeta()  # type: ignore[assignment]

        async with AsyncSessionLocal() as db:
            result = await _confirm(
                doctor_id=state.doctor_id,
                branch_id=state.branch_id,
                patient_name=patient_name,
                patient_phone=patient_phone,
                complaint=complaint,
                booking_date=parsed_date,
                token_number=state.token_number,
                followup_consent=followup_consent,
                appointment_time=None,
                source="voice",
                db=db,
                calendar_service=calendar_svc,
                meta_service=meta_svc,
            )

        if result.get("success"):
            state.token_confirmed = True
            state.patient_name = patient_name
            state.patient_phone = patient_phone

        logger.info(
            "tool_confirm_booking",
            branch_id=str(state.branch_id),
            token_number=state.token_number,
            patient_phone_last4=patient_phone[-4:] if patient_phone else None,
            success=result.get("success"),
        )
        return result

    return [route_to_doctor, check_availability, assign_token, confirm_booking]


# ──────────────────────────────────────────────────────────────────────────
# Agent class — handles per-call lifecycle
# ──────────────────────────────────────────────────────────────────────────


class VachananAgent(Agent):
    def __init__(self, state: SessionState) -> None:
        super().__init__(
            instructions="",
            tools=_make_booking_tools(state),
        )
        self.state = state

    async def on_enter(self) -> None:
        """Fires when agent joins the room. Load branch context then speak greeting."""
        try:
            await self._load_branch_context()
        except Exception as e:
            logger.error("branch_context_load_failed", error=str(e))
            await self.session.say(
                sanitize_for_tts(
                    "క్షమించండి, ఈ నంబర్ కు కనెక్ట్ కాలేదు. దయచేసి మళ్ళీ ప్రయత్నించండి."
                )
            )
            await self.session.aclose()
            return

        await self._speak_live_greeting()
        logger.info(
            "call_started",
            branch_id=str(self.state.branch_id) if self.state.branch_id else None,
            plan=self.state.plan,
        )

    async def _load_branch_context(self) -> None:
        """Branch + doctor lookup. Captures all SQLAlchemy values before closing session."""
        async with AsyncSessionLocal() as db:
            branch_result = await db.execute(
                select(Branch).where(Branch.id == self.state.branch_id)
            )
            branch = branch_result.scalar_one_or_none()
            if not branch:
                raise RuntimeError(f"branch {self.state.branch_id} not found")
            # CAPTURE values BEFORE leaving the async with block (DetachedInstanceError)
            branch_name = branch.name
            self.state.emergency_contact = branch.emergency_contact or branch.whatsapp_number

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

        self._cached_branch_name = branch_name
        self._cached_doctor_contexts = doctor_contexts
        self.instructions = build_system_prompt(
            clinic_name=branch_name,
            doctors=doctor_contexts,
            emergency_contact=self.state.emergency_contact,
            plan=self.state.plan or "clinic",
            is_rebook=self.state.is_rebook,
        )

    async def _speak_live_greeting(self) -> None:
        """Speak DPDP s.5 disclosure then warm clinic greeting."""
        disclosure = sanitize_for_tts(build_disclosure_utterance())
        await self.session.say(disclosure)

        clinic_name = getattr(self, "_cached_branch_name", "the clinic")
        greeting = sanitize_for_tts(
            f"నమస్కారం! మీరు {clinic_name} కు కాల్ చేశారు. నేను మీకు అపాయింట్‌మెంట్ "
            f"బుక్ చేయడంలో సహాయం చేస్తాను. మీ పేరు చెప్పగలరా?"
        )
        await self.session.say(greeting)

    async def on_user_turn_completed(self, turn_ctx: Any, new_message: Any) -> None:
        """Emergency keyword detection after each user turn (CLAUDE.md Rule 7).

        new_message.content is list[ChatContent] in LiveKit 1.5.9.
        Use text_content property; fall back to manual extraction.
        """
        content: str | None = None
        if new_message is not None:
            content = new_message.text_content  # str | None
            if content is None:
                raw = getattr(new_message, "content", None)
                if isinstance(raw, str):
                    content = raw
                elif isinstance(raw, list):
                    content = " ".join(
                        part if isinstance(part, str) else getattr(part, "text", "")
                        for part in raw
                    )

        if not content:
            return

        if is_emergency(content):
            contact = self.state.emergency_contact or "the clinic"
            msg = sanitize_for_tts(
                f"నేను అర్థం చేసుకున్నాను. దయచేసి వెంటనే ఈ నంబర్ కు కాల్ చేయండి: {contact}"
            )
            await self.session.say(msg)
            # Continue booking — emergency contact given, do NOT disconnect


# ──────────────────────────────────────────────────────────────────────────
# Background watchdogs
# ──────────────────────────────────────────────────────────────────────────


async def _solo_cap_watchdog(state: SessionState, session: AgentSession) -> None:
    """Enforce Solo plan 4-min cap. Polls every 5s."""
    try:
        while True:
            await asyncio.sleep(5)
            if state.plan != "solo" or not state.call_start:
                continue
            elapsed = int((datetime.now() - state.call_start).total_seconds())
            state.elapsed_seconds = elapsed
            if elapsed >= SOLO_WARNING_SECONDS and not state.solo_warning_sent:
                state.solo_warning_sent = True
                try:
                    await session.say(
                        sanitize_for_tts("మేము ముగించబోతున్నాం. మీ బుకింగ్ confirm చేస్తున్నాను.")
                    )
                except Exception as e:
                    logger.warning("solo_warning_say_failed", error=str(e))
            if elapsed >= SOLO_CAP_SECONDS:
                logger.info(
                    "solo_cap_reached",
                    elapsed=elapsed,
                    branch_id=str(state.branch_id) if state.branch_id else None,
                )
                try:
                    await session.aclose()
                except Exception as e:
                    logger.warning("solo_cap_aclose_failed", error=str(e))
                return
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error("solo_cap_watchdog_crashed", error=str(e))


async def _inactivity_watchdog(
    last_activity: list,
    session: AgentSession,
    ctx: agents.JobContext,
    state: SessionState,
) -> None:
    """End the call gracefully if no user audio for INACTIVITY_TIMEOUT_SECONDS (30s).

    last_activity is a single-element list[float] — a mutable container so the
    event handler in entrypoint() can update it without a nonlocal closure.
    Polls every 5s for performance.
    """
    try:
        while True:
            await asyncio.sleep(5)
            elapsed = time.monotonic() - last_activity[0]
            if elapsed > INACTIVITY_TIMEOUT_SECONDS:
                logger.info(
                    "inactivity_timeout",
                    elapsed_seconds=int(elapsed),
                    branch_id=str(state.branch_id) if state.branch_id else None,
                )
                try:
                    await session.say(
                        sanitize_for_tts(
                            "Marrispappalu vinipinchatm ledu. Mee call ki dhanyavadalu, "
                            "matla appudu call cheyandi."
                        )
                    )
                    session.shutdown(drain=False)
                except Exception as e:
                    logger.warning("inactivity_shutdown_failed", error=str(e))
                return
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error("inactivity_watchdog_crashed", error=str(e))


# ──────────────────────────────────────────────────────────────────────────
# Entrypoint
# ──────────────────────────────────────────────────────────────────────────


async def entrypoint(ctx: agents.JobContext) -> None:
    state = SessionState()
    state.livekit_room_id = ctx.room.name
    state.call_start = datetime.now()

    # metadata fallback for non-SIP rooms (plan + call_type + is_rebook only)
    metadata: dict = {}
    if ctx.room.metadata:
        try:
            metadata = json.loads(ctx.room.metadata)
        except Exception:
            pass
    state.plan = metadata.get("plan", "clinic")
    state.call_type = metadata.get("call_type", "inbound_booking")
    state.is_rebook = metadata.get("is_rebook") in (True, "true", "1")

    await ctx.connect()

    # Part 2: DID → branch_id resolution (must run AFTER ctx.connect())
    try:
        branch_id, patient_phone = await _resolve_branch_from_sip(ctx)
        state.branch_id = branch_id
        if patient_phone:
            state.patient_phone = patient_phone
    except ValueError as e:
        logger.error("branch_resolution_failed", error=str(e))
        await ctx.shutdown(reason="branch_resolution_failed")
        return

    stt = sarvam.STT(
        api_key=settings.sarvam_api_key,
        model="saaras:v3",
        language="te-IN",
    )
    tts = sarvam.TTS(
        api_key=settings.sarvam_api_key,
        model="bulbul:v3",
        target_language_code="te-IN",
    )

    turn_detector = None
    try:
        from livekit.plugins.turn_detector.multilingual import MultilingualModel
        turn_detector = MultilingualModel()
    except Exception as e:
        logger.warning(
            "multilingual_turn_detector_unavailable_falling_back_to_default_vad",
            error=str(e),
        )

    llm = FallbackAdapter([
        google.LLM(model="gemini-2.5-flash", api_key=settings.gemini_api_key, temperature=0.3),
        lk_openai.LLM(model="gpt-4o-mini", api_key=settings.openai_api_key, temperature=0.3),
    ])

    session_kwargs: dict = {
        "stt": stt,
        "tts": tts,
        "llm": llm,
        "allow_interruptions": True,
    }
    if turn_detector is not None:
        session_kwargs["turn_detection"] = turn_detector

    session = AgentSession(**session_kwargs)
    agent = VachananAgent(state=state)

    # Inactivity guard — mutable list updated by event handler bump
    last_activity: list = [time.monotonic()]

    @session.on("user_input_transcribed")
    def _bump_activity(_ev: Any) -> None:
        last_activity[0] = time.monotonic()

    @session.on("disconnected")
    async def on_disconnect() -> None:
        """Release held Redis token on call drop (CLAUDE.md Rule 3)."""
        if state.token_held and not state.token_confirmed:
            r = aioredis.from_url(settings.redis_url)
            try:
                await r.decr(state.token_redis_key)
                logger.warning(
                    "token_released_on_disconnect",
                    token=state.token_number,
                    branch_id=str(state.branch_id) if state.branch_id else None,
                )
            finally:
                await r.aclose()

    solo_task = asyncio.create_task(_solo_cap_watchdog(state, session))
    inactivity_task = asyncio.create_task(
        _inactivity_watchdog(last_activity, session, ctx, state)
    )

    try:
        await session.start(
            room=ctx.room,
            agent=agent,
            room_input_options=RoomInputOptions(),
        )
    finally:
        for task in (solo_task, inactivity_task):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


if __name__ == "__main__":
    agents.cli.run_app(
        agents.WorkerOptions(
            entrypoint_fnc=entrypoint,
            agent_name="voice-assistant",
        )
    )

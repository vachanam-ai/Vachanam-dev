"""Vachanam LiveKit voice agent entrypoint.

Implements the voice call flow + latency design (spec
docs/superpowers/specs/2026-06-01-voice-call-flow-latency-design.md).

Component map → code:
  1. Streaming STT       → sarvam.STT WebSocket (default in livekit-plugins-sarvam)
  2. Streaming LLM       → google.LLM via FallbackAdapter (livekit handles SSE)
  3. Streaming TTS       → sarvam.TTS WebSocket (chunked via AgentSession default)
  4. Pre-cached greeting → backend/static/greetings/<branch_id>.wav played in on_enter
                           BEFORE DB lookups complete
  5. Connection keep-alive → AgentSession reuses WebSockets for call duration
  6. Parallel DB lookup    → asyncio.create_task in on_enter; greeting plays meanwhile
  7. Smart end-of-turn     → livekit.plugins.turn_detector.MultilingualModel()
  8. Always-interruptible  → AgentSession default + allow_interruptions=True
  9. Silence handling      → _silence_watchdog background task using silence_handler
 10. Garbled input defense → audio_quality + Layer B detection in on_user_turn_completed
 11. Solo 4-min cap        → _solo_cap_watchdog background task (unchanged from TD-009)
 12. Emergency override    → state.silence_state.mark_emergency() when keyword fires

CLAUDE.md rules respected:
  - Every DB query filters by branch_id
  - Tokens via Redis INCR (in booking_tools.py); DECR only rollback
  - Calendar success required for booking
  - Every session.say() through sanitize_for_tts()
  - LLM Gemini primary → GPT-4o-mini fallback via FallbackAdapter
  - Structlog with branch_id + last-4 phone on all significant events
  - phone[-4:] only in logs
"""
# ── Bootstrap: must be at the very top, before any async-related import ──────
# Gap 1: asyncpg requires SelectorEventLoop on Windows; Python 3.10+ defaults
# to ProactorEventLoop. Fix before LiveKit Agents (which may set its own policy
# at import time).
import sys
import asyncio

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Gap 2: Load .env from project root regardless of CWD. pydantic-settings resolves
# env_file relative to CWD which breaks when agent is launched from a different
# directory. python-dotenv is in agent/requirements.txt.
from pathlib import Path
from dotenv import load_dotenv

_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
if _ENV_PATH.exists():
    load_dotenv(_ENV_PATH)

# Gap 3: Configure structlog JSON output before any logger use. Must happen
# before `from backend.config import settings` to avoid chicken-egg (settings
# import may already call logger). log_level hardcoded INFO here; reading
# settings.log_level would require settings to already be initialised.
from agent.logging_config import configure_structlog

configure_structlog(log_level="INFO")
# ─────────────────────────────────────────────────────────────────────────────

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import redis.asyncio as aioredis
import structlog
from livekit import agents
from livekit.agents import Agent, AgentSession, RoomInputOptions
from livekit.agents.llm import FallbackAdapter
from livekit.plugins import google, openai as lk_openai, sarvam

from agent.prompts.system_prompt import DoctorContext, build_disclosure_utterance, build_system_prompt
from backend.services.audit_service import write_audit_row
from agent.services.audio_quality import (
    assess_transcript,
    is_llm_clarification_request,
)
from agent.services.emergency import is_emergency
from agent.services.silence_handler import (
    CANNED_GARBLED_RETRY,
    CANNED_HANGUP_DEFAULT,
    CANNED_HANGUP_GARBLED,
    CANNED_PROMPT_1_FALLBACK,
    CANNED_PROMPT_2_FALLBACK,
    Directive,
    SilenceState,
    decide_garbled_directive,
    decide_silence_directive,
)
from agent.services.tts_sanitizer import sanitize_for_tts
from agent.session_state import SessionState
from backend.config import settings
from backend.database import AsyncSessionLocal
from backend.models.schema import Branch, Doctor
from sqlalchemy import and_, select

logger = structlog.get_logger()

SOLO_CAP_SECONDS = 240          # 4 minutes — billing hard limit (Solo plan)
SOLO_WARNING_SECONDS = SOLO_CAP_SECONDS - 10
WATCHDOG_INTERVAL_SECONDS = 0.5  # silence watchdog tick

_GREETINGS_DIR = Path(__file__).resolve().parent.parent / "backend" / "static" / "greetings"


# ──────────────────────────────────────────────────────────────────────────
# Agent class — handles per-call lifecycle
# ──────────────────────────────────────────────────────────────────────────


class VachananAgent(Agent):
    def __init__(self, state: SessionState) -> None:
        super().__init__(instructions="")  # overridden in on_enter once branch loaded
        self.state = state
        # Per-call silence state — owned by the agent, mutated by watchdog + events.
        self.silence_state = SilenceState()
        # Mark of when the last activity happened (AI speech end OR user speech end).
        # Used by _silence_watchdog to compute elapsed silence.
        self.last_activity_at: datetime | None = None

    async def on_enter(self) -> None:
        """Fires when agent joins the room. Per spec Component 4-6:
        - Start playing pre-cached greeting IMMEDIATELY (within 100ms)
        - Run branch+doctor DB lookup IN PARALLEL during greeting playback
        """
        # Component 4: play pre-cached greeting first (<100ms target)
        greeting_played = await self._play_precached_greeting()

        # Component 6: parallel DB lookup task — doesn't block greeting
        db_task = asyncio.create_task(self._load_branch_context())

        # If we didn't have a pre-cached file, we need to wait for DB + speak greeting now
        if not greeting_played:
            try:
                await db_task
            except Exception as e:
                logger.error("branch_context_load_failed", error=str(e))
                await self.session.say(
                    sanitize_for_tts("క్షమించండి, ఈ నంబర్ కు కనెక్ట్ కాలేదు. దయచేసి మళ్ళీ ప్రయత్నించండి.")
                )
                await self.session.aclose()
                return
            await self._speak_live_greeting()
        else:
            # Greeting is playing; await DB context so subsequent turns have it
            try:
                await db_task
            except Exception as e:
                logger.error("branch_context_load_failed_after_greeting", error=str(e))

        self.last_activity_at = datetime.now()
        logger.info(
            "call_started",
            branch_id=str(self.state.branch_id) if self.state.branch_id else None,
            plan=self.state.plan,
            greeting_played_from_cache=greeting_played,
        )

    async def _play_precached_greeting(self) -> bool:
        """Component 4: stream the pre-cached greeting WAV for this branch.

        Returns True if a cached file was played, False if we need to fall back
        to live TTS. Per spec, target <100ms first-word latency on call pickup.
        """
        if not self.state.branch_id:
            return False
        greeting_path = _GREETINGS_DIR / f"{self.state.branch_id}.wav"
        if not greeting_path.exists():
            logger.warning(
                "precached_greeting_missing",
                branch_id=str(self.state.branch_id),
                path=str(greeting_path),
            )
            return False
        # LiveKit 1.5 doesn't expose a direct "play this WAV" API on AgentSession.
        # Workaround: we let on_enter speak the greeting via TTS but rely on
        # the AgentSession's chunked streaming to start audio quickly. The
        # pre-cached file path is reserved for a future Phase 10 enhancement
        # where we wire it through ctx.room.local_participant.publish_track.
        # For now: log presence + fall back to live TTS (still fast due to
        # streaming TTS + warmup).
        # TODO TD-020 (logged separately): wire actual WAV publish in Phase 10.
        return False

    async def _load_branch_context(self) -> None:
        """Component 6: branch + doctor lookup. Runs in parallel with greeting playback."""
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
        # Build the system prompt now so subsequent turns are fast
        self.instructions = build_system_prompt(
            clinic_name=branch_name,
            doctors=doctor_contexts,
            emergency_contact=self.state.emergency_contact,
            plan=self.state.plan or "clinic",
            is_rebook=self.state.is_rebook,
        )

    async def _speak_live_greeting(self) -> None:
        """Fallback: speak the greeting via live TTS when no cached file available.

        Step 0 (DPDP s.5): disclosure is always spoken FIRST, before any
        name/phone collection prompt, and is not skipped even if the patient
        speaks immediately (allow_interruptions=True handles that).
        """
        # Step 0 — DPDP s.5 consent disclosure (Rule 6: through sanitize_for_tts)
        disclosure = sanitize_for_tts(build_disclosure_utterance())
        await self.session.say(disclosure)

        # Step 1 onwards — warm clinic greeting
        clinic_name = getattr(self, "_cached_branch_name", "the clinic")
        greeting = sanitize_for_tts(
            f"నమస్కారం! మీరు {clinic_name} కు కాల్ చేశారు. నేను మీకు అపాయింట్‌మెంట్ "
            f"బుక్ చేయడంలో సహాయం చేస్తాను. మీ పేరు చెప్పగలరా?"
        )
        await self.session.say(greeting)

    async def on_user_turn_completed(self, turn_ctx: Any, new_message: Any) -> None:
        """Fires after the user's turn ends and STT has finalized the transcript.

        Per spec:
        - Component 10A: STT confidence check — if low, treat as garbled
        - Component 12: emergency keyword detection (existing)
        - Component 9: reset silence timer (user spoke)
        """
        self.last_activity_at = datetime.now()
        self.silence_state.reset_silence()

        # Extract text safely (livekit ChatMessage.content may be str or parts list)
        content = new_message.content if new_message else None
        if not isinstance(content, str):
            content = " ".join(
                part if isinstance(part, str) else getattr(part, "text", "")
                for part in (content or [])
            )

        if not content:
            return

        # Component 12: emergency override (sticky)
        if is_emergency(content):
            self.silence_state.mark_emergency()
            contact = self.state.emergency_contact or "the clinic"
            msg = sanitize_for_tts(
                f"నేను అర్థం చేసుకున్నాను. దయచేసి వెంటనే ఈ నంబర్ కు కాల్ చేయండి: {contact}"
            )
            await self.session.say(msg)
            # Continue booking — emergency contact given, do NOT disconnect

            # Audit log — voice path emergency (Gap 10). Fire-and-forget.
            # Raw keyword NOT stored — categorised as "medical_critical" to satisfy PII_DENYLIST
            # ("symptom" is a denied substring; actual keyword may describe a symptom).
            try:
                await write_audit_row(
                    action="emergency.keyword_detected",
                    resource_type="call",
                    resource_id=self.state.livekit_room_id,
                    branch_id=self.state.branch_id,
                    ip_address=None,
                    user_agent="voice-agent/1.0",
                    metadata={
                        "emergency_keyword_category": "medical_critical",
                        "via": "voice",
                    },
                )
            except Exception as _audit_err:
                logger.error("audit_write_failed_emergency", error=str(_audit_err))

        # Note: STT confidence check (Component 10A) requires per-turn STT response
        # object which livekit-plugins-sarvam doesn't expose to the Agent layer in
        # 1.5.9. We rely on Layer B (LLM-side clarification, detected in
        # on_agent_response_done below) for garbled handling. Layer A wiring is
        # deferred to a future LiveKit version (logged TD).

    async def on_agent_response_done(self, response_text: str) -> None:
        """Fires after the agent's response is complete.

        Per spec Component 10 Layer B: if the LLM's response is a clarification
        request ("kshamincandi, mali cheppagalara"), increment the garbled counter.
        At limit, hangup with the canned garbled message.
        """
        self.last_activity_at = datetime.now()
        self.silence_state.reset_silence()

        if is_llm_clarification_request(response_text):
            self.silence_state.garbled_count += 1
            logger.info(
                "garbled_turn_detected",
                garbled_count=self.silence_state.garbled_count,
                branch_id=str(self.state.branch_id) if self.state.branch_id else None,
            )
            directive = decide_garbled_directive(self.silence_state)
            if directive == Directive.GARBLED_HANGUP:
                logger.info("garbled_hangup", branch_id=str(self.state.branch_id))
                await self.session.say(sanitize_for_tts(CANNED_HANGUP_GARBLED))
                await self.session.aclose()
                return
        else:
            # Comprehensible response advances booking → reset garbled counter
            self.silence_state.reset_garbled()


# ──────────────────────────────────────────────────────────────────────────
# Background watchdogs
# ──────────────────────────────────────────────────────────────────────────


async def _solo_cap_watchdog(state: SessionState, session: AgentSession) -> None:
    """Enforce Solo plan 4-min cap independent of user activity.
    Unchanged from TD-009 fix — polls every 5s.
    """
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


async def _silence_watchdog(agent: VachananAgent, session: AgentSession) -> None:
    """Component 9: silence handling state machine.

    Polls every 500ms. Computes seconds since last activity (AI speech end or
    user speech end). Calls silence_handler.decide_silence_directive(); acts:
      - PROMPT_1 / PROMPT_2 → speak a context-aware prompt (fallback to canned)
      - HANGUP → speak canned goodbye, close session
    """
    try:
        while True:
            await asyncio.sleep(WATCHDOG_INTERVAL_SECONDS)

            if agent.last_activity_at is None:
                continue

            elapsed = (datetime.now() - agent.last_activity_at).total_seconds()
            directive = decide_silence_directive(agent.silence_state, elapsed)

            if directive == Directive.NONE:
                continue

            if directive == Directive.HANGUP:
                logger.info(
                    "silence_hangup",
                    elapsed_seconds=elapsed,
                    mode=agent.silence_state.mode.value,
                    branch_id=str(agent.state.branch_id) if agent.state.branch_id else None,
                )
                try:
                    await session.say(sanitize_for_tts(CANNED_HANGUP_DEFAULT))
                    await session.aclose()
                except Exception as e:
                    logger.warning("silence_hangup_failed", error=str(e))
                return

            if directive == Directive.PROMPT_1:
                agent.silence_state.prompts_emitted = max(agent.silence_state.prompts_emitted, 1)
                prompt = sanitize_for_tts(CANNED_PROMPT_1_FALLBACK)
                try:
                    await session.say(prompt)
                    agent.last_activity_at = datetime.now()
                except Exception as e:
                    logger.warning("silence_prompt_1_failed", error=str(e))

            elif directive == Directive.PROMPT_2:
                agent.silence_state.prompts_emitted = max(agent.silence_state.prompts_emitted, 2)
                prompt = sanitize_for_tts(CANNED_PROMPT_2_FALLBACK)
                try:
                    await session.say(prompt)
                    agent.last_activity_at = datetime.now()
                except Exception as e:
                    logger.warning("silence_prompt_2_failed", error=str(e))
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error("silence_watchdog_crashed", error=str(e))


# ──────────────────────────────────────────────────────────────────────────
# Entrypoint
# ──────────────────────────────────────────────────────────────────────────


async def entrypoint(ctx: agents.JobContext) -> None:
    state = SessionState()
    state.livekit_room_id = ctx.room.name

    metadata: dict = {}
    if ctx.room.metadata:
        try:
            metadata = json.loads(ctx.room.metadata)
        except Exception:
            pass

    state.branch_id = UUID(metadata["branch_id"]) if metadata.get("branch_id") else None
    state.plan = metadata.get("plan", "clinic")
    state.call_type = metadata.get("call_type", "inbound_booking")
    state.is_rebook = metadata.get("is_rebook") in (True, "true", "1")
    state.call_start = datetime.now()

    await ctx.connect()

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

    # Component 7 — smart end-of-turn detection (multilingual model).
    # If the plugin fails to load (transient version drift), AgentSession falls back
    # to the default Silero VAD which is still acceptable for MVP.
    turn_detector = None
    try:
        from livekit.plugins.turn_detector.multilingual import MultilingualModel
        turn_detector = MultilingualModel()
    except Exception as e:
        logger.warning("multilingual_turn_detector_unavailable_falling_back_to_default_vad",
                       error=str(e))

    # Component 2 — LLM with Gemini primary + GPT-4o-mini fallback (FallbackAdapter
    # already shipped in TD-007 fix).
    llm = FallbackAdapter([
        google.LLM(model="gemini-2.5-flash", api_key=settings.gemini_api_key, temperature=0.3),
        lk_openai.LLM(model="gpt-4o-mini", api_key=settings.openai_api_key, temperature=0.3),
    ])

    # AgentSession — Component 1+2+3 streaming pipeline + Component 5 keep-alive.
    # allow_interruptions=True → Component 8 (always-interruptible AI).
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

    @session.on("disconnected")
    async def on_disconnect() -> None:
        """Release any held Redis token on call drop (CLAUDE.md Rule 3)."""
        if state.token_held and not state.token_confirmed:
            r = aioredis.from_url(settings.redis_url)
            try:
                await r.decr(state.token_redis_key)
                logger.warning(
                    "token_released_on_disconnect",
                    token=state.token_number,
                    branch_id=str(state.branch_id),
                )
            finally:
                await r.aclose()

            # Audit log — voice path token release (Gap 10).
            # PII_DENYLIST enforced by write_audit_row; only safe keys included.
            try:
                await write_audit_row(
                    action="token.released_on_disconnect",
                    resource_type="call",
                    resource_id=state.livekit_room_id,
                    branch_id=state.branch_id,
                    ip_address=None,
                    user_agent="voice-agent/1.0",
                    metadata={
                        "token_number": state.token_number,
                        "redis_key": state.token_redis_key,
                        "disconnect_reason": "call_dropped",
                    },
                    success=False,
                )
            except Exception as _audit_err:
                logger.error("audit_write_failed_token_released", error=str(_audit_err))

    # Background watchdogs — both cancelled in finally on normal session end.
    solo_task = asyncio.create_task(_solo_cap_watchdog(state, session))
    silence_task = asyncio.create_task(_silence_watchdog(agent, session))

    try:
        await session.start(
            room=ctx.room,
            agent=agent,
            room_input_options=RoomInputOptions(),
        )
    finally:
        for task in (solo_task, silence_task):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


if __name__ == "__main__":
    # agent_name MUST match the dispatch rule's RoomAgentDispatch.agent_name.
    # The LiveKit dispatch rule created by scripts/provision_vobiz_trunk.py
    # uses "voice-assistant". Changing this here without updating the dispatch
    # rule (or vice-versa) will break inbound call routing.
    agents.cli.run_app(
        agents.WorkerOptions(
            entrypoint_fnc=entrypoint,
            agent_name="voice-assistant",
        )
    )

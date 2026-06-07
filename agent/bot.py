"""Pipecat pipeline core for Vachanam voice agent.

Entrypoint: run_pipeline(websocket, call_id, did, caller)

Pipeline order (per spec §4 + CLAUDE.md rules):
  transport.input()
  -> SarvamSTTService (saaras:v3, te-IN)
  -> LLMUserAggregator  (VAD on aggregator per Pipecat 1.x telephony requirement)
  -> GoogleLLMService (gemini-2.5-flash, stub for Task 7 fallback adapter)
  -> LLMAssistantAggregator
  -> SarvamTTSService (bulbul:v3, te-IN)
  -> transport.output()

Import-path corrections vs original plan (pipecat-ai 1.3.0 verified):
- PipelineTask/PipelineRunner deprecated -> PipelineWorker/WorkerRunner
- LLMUserAggregator, LLMAssistantAggregator, LLMUserAggregatorParams,
  LLMContextAggregatorPair in pipecat.processors.aggregators.llm_response_universal
  (NOT pipecat.processors.aggregators.llm_response, which only has LLMFullResponseAggregator)
- VobizFrameSerializer (not ProtobufFrameSerializer) from pipecat.serializers.vobiz
- No allow_interruptions param on PipelineWorker — barge-in controlled by VAD
- Language import: from pipecat.transcriptions.language import Language
- handle_sigint=False on WorkerRunner — embedded in FastAPI, not a standalone process

CLAUDE.md rules enforced here:
- RULE 1: Doctor query includes Doctor.branch_id == branch.id
- RULE 2/3: Redis INCR/DECR token management — DECR is rollback only
- RULE 5: Branch resolved from dialed DID, never from caller
- RULE 6: All TTS text goes through sanitize_for_tts() (wired in Task 8)
- RULE 9: Gemini primary; Task 7 wraps with GPT-4o-mini fallback adapter
- RULE 10: Structlog on every meaningful event (call_started, branch_resolved, etc.)
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketTransport,
    FastAPIWebsocketParams,
)
from pipecat.serializers.vobiz import VobizFrameSerializer
from pipecat.services.sarvam.stt import SarvamSTTService, SarvamSTTSettings
from pipecat.services.sarvam.tts import SarvamTTSService, SarvamTTSSettings
from pipecat.services.google.llm import GoogleLLMService
from pipecat.services.openai.llm import OpenAILLMService  # noqa: F401 — used in Task 7 fallback
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineWorker, PipelineParams  # PipelineTask deprecated
from pipecat.pipeline.runner import WorkerRunner  # PipelineRunner deprecated
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.transcriptions.language import Language

from agent.session_state import SessionState
from backend.config import settings
from backend.database import AsyncSessionLocal
from backend.models.schema import Branch, Doctor

logger = structlog.get_logger()


# ─── Branch resolution ────────────────────────────────────────────────────────


async def resolve_branch_or_raise(db: AsyncSession, did: str) -> Branch:
    """Look up Branch by did_number. Raises ValueError if unknown.

    CLAUDE.md RULE 5: branch comes from dialed DID, never from caller phone.
    The `caller` arg is deliberately excluded from this function's signature.
    """
    result = await db.execute(
        select(Branch).where(Branch.did_number == did)
    )
    branch = result.scalar_one_or_none()
    if branch is None:
        logger.warning("unknown_did", did=did[-4:])
        raise ValueError(f"unknown DID: {did}")
    return branch


# ─── Service builders ─────────────────────────────────────────────────────────


def build_stt_service(api_key: str) -> SarvamSTTService:
    """Build Sarvam Saaras v3 STT for Telugu (te-IN).

    keepalive_interval=5.0 is set per Pipecat issue #3699 mitigation:
    Sarvam STT WebSocket can silently die on long silences; keepalive
    prevents the connection from dropping.
    """
    return SarvamSTTService(
        api_key=api_key,
        settings=SarvamSTTSettings(
            model="saaras:v3",
            language=Language.TE_IN,
        ),
        keepalive_interval=5.0,
    )


def build_tts_service(api_key: str) -> SarvamTTSService:
    """Build Sarvam Bulbul v3 TTS for Telugu with Anushka voice."""
    return SarvamTTSService(
        api_key=api_key,
        settings=SarvamTTSSettings(
            model="bulbul:v3",
            language=Language.TE_IN,
            voice="anushka",
        ),
    )


def build_llm_with_fallback(gemini_key: str, openai_key: str) -> GoogleLLMService:
    """Build LLM service. STUB for Task 7.

    Task 7 replaces this with a fallback adapter wrapping Gemini primary
    and GPT-4o-mini secondary (CLAUDE.md RULE 9). For Task 6 the stub
    returns a plain GoogleLLMService configured for gemini-2.5-flash.
    The openai_key parameter is accepted (not used yet) so the Task 7
    signature is stable.
    """
    _ = openai_key  # Task 7 wires the fallback adapter
    return GoogleLLMService(
        api_key=gemini_key,
        settings=GoogleLLMService.Settings(model="gemini-2.5-flash"),
    )


def build_transport(
    websocket: Any,
    public_url: str,  # noqa: ARG001 — used by server for WebSocket URL; kept for call-site clarity
    stream_id: str,
    call_id: str,
) -> FastAPIWebsocketTransport:
    """Build FastAPI WebSocket transport with Vobiz frame serializer.

    add_wav_header=False is CRITICAL for telephony (μ-law 8kHz stream).
    Per Vobiz-X-Pipecat README: never add WAV header on an in-band audio stream.
    session_timeout=900 allows up to 15-minute calls before Pipecat force-closes.
    """
    serializer = VobizFrameSerializer(
        stream_id=stream_id,
        call_id=call_id,
        auth_id=settings.vobiz_auth_id or None,
        auth_token=settings.vobiz_auth_token or None,
    )
    return FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            add_wav_header=False,  # CRITICAL — telephony requirement
            serializer=serializer,
            session_timeout=900,
        ),
    )


# ─── Tool stubs (filled in Task 7 and Task 9) ────────────────────────────────


def register_tools(llm: Any, **kwargs: Any) -> None:
    """Register LLM function tools. STUB — Task 7 fills this.

    Task 7 will register 5 tools via FunctionSchema + llm.register_function():
      route_to_doctor, check_availability, assign_token, confirm_booking,
      request_human_transfer.

    All kwargs (db_session, redis_client, calendar_service, meta_service,
    session_state, signal_map, branch_emergency_contact, tts_say) are
    accepted here so the call site in run_pipeline() is stable across tasks.
    """
    pass  # Task 7


async def release_token_on_disconnect(
    state: SessionState,
    redis_client: Any,
) -> None:
    """Release a held, unconfirmed token via Redis DECR on disconnect. STUB for Task 9.

    CLAUDE.md RULE 3: if call drops without token_confirmed, roll back via DECR.
    DECR is rollback-only — never used as primary token allocation (that uses INCR).
    Task 9 wires this into the server's /ws disconnect handler AND into
    run_pipeline's try/finally block.

    The stub exists here so Task 9 has a stable import target and tests can
    assert the function is async (see test_bot_pipeline_builder.py).
    """
    if redis_client is None:
        return
    if state.token_held and not state.token_confirmed and state.token_redis_key:
        await redis_client.decr(state.token_redis_key)
        logger.warning(
            "token_released_on_disconnect",
            token=state.token_number,
            branch_id=str(state.branch_id),
            session_id=state.session_id,
        )


# ─── Pipeline orchestrator ────────────────────────────────────────────────────


async def run_pipeline(
    websocket: Any,
    call_id: str,
    did: str,
    caller: str,
) -> None:
    """Run the per-call Pipecat pipeline.

    One invocation per inbound WebSocket connection. Called from agent/server.py:/ws.
    Opens its own DB session; closes it in finally regardless of outcome.
    Token release on disconnect is wired in the finally block via the release_token
    stub (Task 9 fills real Redis client).

    CLAUDE.md RULE 5: branch resolved from dialed DID (did param), never from caller.
    CLAUDE.md RULE 1: Doctor query filters by branch_id.
    CLAUDE.md RULE 10: structlog on call_started, branch_resolved, pipeline_built.

    Pipeline order (per spec §4 + architecture doc):
      transport.input()
      -> STT (Sarvam saaras:v3 te-IN)
      -> LLMUserAggregator (with SileroVAD — barge-in detection)
      -> GoogleLLMService (gemini-2.5-flash; Task 7 adds GPT-4o-mini fallback)
      -> LLMAssistantAggregator
      -> SarvamTTSService (bulbul:v3 te-IN)
      -> transport.output()

    Args:
        websocket: FastAPI WebSocket connection from the /ws endpoint.
        call_id: Vobiz call identifier, passed as query param ?call_id=X.
        did: Dialed DID number (the clinic's phone number), from ?to=DID query param.
        caller: Caller's phone number (masked in logs), from ?from=CALLER query param.
    """
    logger.info(
        "call_started",
        call_id=call_id,
        did=did[-4:],
        caller=caller[-4:] if caller else "unknown",
    )

    # Per-call state — never module-level (CLAUDE.md guardrail)
    state = SessionState(
        session_id=call_id,
        call_start=datetime.utcnow(),
        patient_phone=caller,
    )

    db: AsyncSession = AsyncSessionLocal()
    try:
        # ── 1. Resolve branch from dialed DID (RULE 5) ────────────────────
        branch = await resolve_branch_or_raise(db, did)

        # Capture SQLAlchemy attributes before any async context switch
        # (CLAUDE.md: capture attrs into local vars BEFORE exiting async with)
        branch_id = branch.id
        branch_name = branch.name
        branch_emergency_contact = branch.emergency_contact

        state.branch_id = branch_id
        state.emergency_contact = branch_emergency_contact

        logger.info(
            "branch_resolved",
            branch_id=str(branch_id),
            branch_name=branch_name,
            did=did[-4:],
        )

        # ── 2. Load active doctors for branch (RULE 1: filter by branch_id) ─
        result = await db.execute(
            select(Doctor).where(
                and_(
                    Doctor.branch_id == branch_id,
                    Doctor.status == "active",
                )
            )
        )
        doctors = result.scalars().all()

        # ── 3. Build transport (add_wav_header=False is non-negotiable) ──────
        transport = build_transport(
            websocket=websocket,
            public_url=settings.public_url,
            stream_id=call_id,
            call_id=call_id,
        )

        # ── 4. Build services ─────────────────────────────────────────────────
        stt = build_stt_service(settings.sarvam_api_key)
        llm = build_llm_with_fallback(settings.gemini_api_key, settings.openai_api_key)
        tts = build_tts_service(settings.sarvam_api_key)

        # ── 5. Register tools (stub — Task 7 fills) ───────────────────────────
        register_tools(
            llm,
            db_session=db,
            session_state=state,
            branch_emergency_contact=branch_emergency_contact,
        )

        # ── 6. Build LLM context + aggregators ───────────────────────────────
        # VAD on LLMUserAggregatorParams — Pipecat 1.x telephony requirement.
        # transport.params does NOT take a vad_analyzer in 1.x.
        context = LLMContext(messages=[])

        user_params = LLMUserAggregatorParams(
            vad_analyzer=SileroVADAnalyzer(),
        )

        agg_pair = LLMContextAggregatorPair(
            context,
            user_params=user_params,
        )

        # ── 7. Build pipeline ─────────────────────────────────────────────────
        pipeline = Pipeline(
            [
                transport.input(),
                stt,
                agg_pair.user(),
                llm,
                agg_pair.assistant(),
                tts,
                transport.output(),
            ]
        )

        logger.info(
            "pipeline_built",
            branch_id=str(branch_id),
            session_id=call_id,
            doctor_count=len(doctors),
        )

        # ── 8. Run pipeline ───────────────────────────────────────────────────
        # PipelineTask is deprecated in 1.3.0; use PipelineWorker + WorkerRunner.
        # handle_sigint=False: we are embedded in FastAPI, not a standalone process.
        worker = PipelineWorker(pipeline)
        runner = WorkerRunner(handle_sigint=False)
        runner.add_workers(worker)
        await runner.run()

    except ValueError as e:
        # Unknown DID — log and exit cleanly (no token to release)
        logger.error("pipeline_aborted_unknown_did", error=str(e), did=did[-4:])
        raise
    except Exception as e:
        logger.error(
            "pipeline_error",
            session_id=call_id,
            error=str(e),
            branch_id=str(state.branch_id) if state.branch_id else "unknown",
        )
        raise
    finally:
        # Token rollback on disconnect (CLAUSE.md RULE 3).
        # Real Redis client is wired in Task 9; stub is safe to call with None
        # (the stub checks token_held before doing anything with redis_client).
        # For Task 6 we call the stub — Task 9 passes the real client from /ws.
        await release_token_on_disconnect(state, redis_client=None)

        await db.close()
        logger.info(
            "pipeline_finished",
            session_id=call_id,
            branch_id=str(state.branch_id) if state.branch_id else "unknown",
        )

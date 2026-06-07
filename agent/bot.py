"""Pipecat pipeline core for Vachanam voice agent.

Entrypoint: run_pipeline(websocket, call_id, did, caller)

Pipeline order (per spec §4 + CLAUDE.md rules):
  transport.input()
  -> SarvamSTTService (saaras:v3, te-IN)
  -> LLMUserAggregator  (VAD on aggregator per Pipecat 1.x telephony requirement)
  -> GeminiFallbackLLMService (gemini-2.5-flash primary; GPT-4o-mini fallback)
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
- LLMFallbackAdapter does NOT exist in Pipecat 1.3.0 — custom GeminiFallbackLLMService
  subclasses GoogleLLMService to remain isinstance-compatible with the pipeline.
  It overrides register_function to register on both primary (self) and fallback OpenAI,
  and overrides _process_context to retry with OpenAI on Gemini error.
- FunctionCallParams: from pipecat.services.llm_service import FunctionCallParams
- FunctionSchema: from pipecat.adapters.schemas.function_schema import FunctionSchema
- register_function(name, handler) — confirmed signature in 1.3.0

CLAUDE.md rules enforced here:
- RULE 1: Doctor query includes Doctor.branch_id == branch.id
- RULE 2/3: Redis INCR/DECR token management — DECR is rollback only
- RULE 3: request_human_transfer handler releases held-unconfirmed token via DECR
- RULE 5: Branch resolved from dialed DID, never from caller
- RULE 6: All TTS text in request_human_transfer goes through sanitize_for_tts()
- RULE 9: Gemini primary; GeminiFallbackLLMService wraps GPT-4o-mini as secondary
- RULE 10: Structlog on every meaningful event (call_started, branch_resolved, etc.)
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Callable

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
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.llm_service import FunctionCallParams  # noqa: F401 — used by handlers
from pipecat.adapters.schemas.function_schema import FunctionSchema
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

from agent.services.tts_sanitizer import sanitize_for_tts
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


class GeminiFallbackLLMService(GoogleLLMService):
    """Gemini 2.5 Flash LLM service with GPT-4o-mini as automatic fallback.

    Subclasses GoogleLLMService so it is isinstance-compatible with the Pipeline
    (which expects an LLMService at the LLM position). No Pipecat LLMFallbackAdapter
    exists in 1.3.0 — this custom subclass is the correct pattern.

    Design:
    - Primary inference: Gemini 2.5 Flash (inherited via GoogleLLMService)
    - Fallback inference: GPT-4o-mini (stored as self._fallback_service)
    - register_function: registers handlers on BOTH primary and fallback so
      tool calls work regardless of which model is active at runtime.
    - _process_context: tries Gemini; on any exception logs and re-routes
      to OpenAI by calling the fallback's _process_context with the same frame.

    CLAUDE.md RULE 9: Gemini primary → GPT-4o-mini fallback. Order is NON-NEGOTIABLE.
    """

    def __init__(self, gemini_key: str, openai_key: str) -> None:
        super().__init__(
            api_key=gemini_key,
            settings=GoogleLLMService.Settings(model="gemini-2.5-flash"),
        )
        self._fallback_service: OpenAILLMService = OpenAILLMService(
            api_key=openai_key,
            settings=OpenAILLMService.Settings(model="gpt-4o-mini"),
        )
        self._logger = structlog.get_logger()

    def register_function(
        self,
        function_name: str | None,
        handler: Any,
        *,
        cancel_on_interruption: bool = True,
        timeout_secs: float | None = None,
    ) -> None:
        """Register tool handler on both primary (Gemini) and fallback (OpenAI).

        Ensures the handler fires correctly regardless of which LLM processes
        the inference turn at runtime.
        """
        super().register_function(
            function_name,
            handler,
            cancel_on_interruption=cancel_on_interruption,
            timeout_secs=timeout_secs,
        )
        self._fallback_service.register_function(
            function_name,
            handler,
            cancel_on_interruption=cancel_on_interruption,
            timeout_secs=timeout_secs,
        )

    async def _process_context(self, context: LLMContext) -> None:  # type: ignore[override]
        """Run Gemini inference; on error, fall back to GPT-4o-mini.

        CLAUDE.md RULE 9: Gemini is always tried first. OpenAI fallback is
        only activated on Gemini exception. If both fail, error propagates up.
        """
        try:
            await super()._process_context(context)
        except Exception as primary_exc:
            self._logger.error(
                "gemini_failed_switching_to_openai",
                error=str(primary_exc),
            )
            try:
                await self._fallback_service._process_context(context)
            except Exception as fallback_exc:
                self._logger.critical(
                    "both_llms_failed",
                    gemini_error=str(primary_exc),
                    openai_error=str(fallback_exc),
                )
                raise


def build_llm_with_fallback(gemini_key: str, openai_key: str) -> GeminiFallbackLLMService:
    """Build Gemini 2.5 Flash LLM with GPT-4o-mini automatic fallback.

    Returns a GeminiFallbackLLMService which is a GoogleLLMService subclass
    (isinstance-compatible with the pipeline). Registers tool handlers on both
    primary and fallback services.

    CLAUDE.md RULE 9: Gemini primary → GPT-4o-mini fallback. Non-negotiable order.

    LLMFallbackAdapter does NOT exist in Pipecat 1.3.0. GeminiFallbackLLMService
    is the custom wrapper built per the task spec.
    """
    return GeminiFallbackLLMService(gemini_key=gemini_key, openai_key=openai_key)


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


# ─── Tool schemas and handlers (Task 7) ──────────────────────────────────────


def build_function_schemas() -> list[FunctionSchema]:
    """Build FunctionSchema definitions for all 5 LLM tools.

    Returns schemas for: route_to_doctor, check_availability, assign_token,
    confirm_booking, request_human_transfer.

    Properties follow JSON-schema style. All descriptions are crafted so the
    LLM understands when and how to call each tool.
    """
    return [
        FunctionSchema(
            name="route_to_doctor",
            description=(
                "Match patient complaint to best-fit active doctor for this branch. "
                "Call once after patient states their issue."
            ),
            properties={
                "complaint": {
                    "type": "string",
                    "description": (
                        "Patient health complaint in Telugu/Hindi/English, verbatim. "
                        "Do not translate or paraphrase."
                    ),
                },
            },
            required=["complaint"],
        ),
        FunctionSchema(
            name="check_availability",
            description=(
                "Check whether the selected doctor has capacity on the given date. "
                "Always call before assign_token."
            ),
            properties={
                "doctor_id": {
                    "type": "string",
                    "description": "UUID from route_to_doctor result.",
                },
                "booking_date": {
                    "type": "string",
                    "format": "date",
                    "description": "Booking date in ISO YYYY-MM-DD format.",
                },
                "query_start": {
                    "type": "string",
                    "format": "time",
                    "description": "Optional HH:MM range start for appointment-type doctors.",
                },
                "query_end": {
                    "type": "string",
                    "format": "time",
                    "description": "Optional HH:MM range end for appointment-type doctors.",
                },
            },
            required=["doctor_id", "booking_date"],
        ),
        FunctionSchema(
            name="assign_token",
            description=(
                "Atomically reserve next token via Redis INCR. "
                "Only call after check_availability confirms capacity AND patient agreed to date."
            ),
            properties={
                "doctor_id": {
                    "type": "string",
                    "description": "UUID of the doctor to assign a token for.",
                },
                "booking_date": {
                    "type": "string",
                    "format": "date",
                    "description": "Confirmed booking date in ISO YYYY-MM-DD format.",
                },
                "appointment_time": {
                    "type": "string",
                    "format": "time",
                    "description": (
                        "Required for appointment-type doctors only. HH:MM format."
                    ),
                },
            },
            required=["doctor_id", "booking_date"],
        ),
        FunctionSchema(
            name="confirm_booking",
            description=(
                "Persist booking: DB row + Google Calendar event + WhatsApp send. "
                "Call only after assign_token succeeded AND patient verbally confirmed."
            ),
            properties={
                "doctor_id": {
                    "type": "string",
                    "description": "UUID of the assigned doctor.",
                },
                "patient_name": {
                    "type": "string",
                    "description": "Full name as spoken by the patient.",
                },
                "patient_phone": {
                    "type": "string",
                    "description": (
                        "Patient phone in E.164 format (e.g. +919876543210). "
                        "Omit if patient declined to share."
                    ),
                },
                "complaint": {
                    "type": "string",
                    "description": "Patient health complaint verbatim.",
                },
                "booking_date": {
                    "type": "string",
                    "format": "date",
                    "description": "Confirmed booking date in ISO YYYY-MM-DD format.",
                },
                "token_number": {
                    "type": "integer",
                    "description": "Token number returned by assign_token.",
                },
                "followup_consent": {
                    "type": "boolean",
                    "description": "Whether patient agreed to follow-up calls.",
                },
                "appointment_time": {
                    "type": "string",
                    "format": "time",
                    "description": "HH:MM appointment time for appointment-type doctors.",
                },
            },
            required=[
                "doctor_id",
                "patient_name",
                "complaint",
                "booking_date",
                "token_number",
                "followup_consent",
            ],
        ),
        FunctionSchema(
            name="request_human_transfer",
            description=(
                "Call ONLY when patient explicitly asks to speak to a human/doctor/receptionist, "
                "OR has repeatedly insisted across multiple turns despite booking offers. "
                "Do NOT call for medical-sounding words alone (e.g. 'chest pain', 'heart attack'). "
                "Only for clear intent to bypass the AI. After calling, do not say anything else."
            ),
            properties={
                "reason": {
                    "type": "string",
                    "description": (
                        "Brief justification: 'explicit_ask' for a single clear request, "
                        "or 'persistent_pressure: <short summary>' for repeated insistence."
                    ),
                },
            },
            required=["reason"],
        ),
    ]


def make_request_human_transfer_handler(
    session_state: SessionState,
    redis_client: Any,
    signal_map: dict[str, bool],
    audit_writer: Callable[..., Any],
    branch_emergency_contact: str,
    tts_say: Callable[[str], Any],
) -> Callable[[Any], Any]:
    """Factory: returns an async handler for the request_human_transfer LLM tool.

    The returned handler:
    1. Speaks a brief Telugu confirmation via sanitize_for_tts(). CLAUDE.md RULE 6.
    2. Writes audit_log row with reason and MASKED emergency contact (last 4 only).
       Full phone NEVER logged. Audit failure is caught and logged — never blocks transfer.
    3. Releases any held-unconfirmed token via Redis DECR. CLAUDE.md RULE 3.
       Confirmed tokens are NEVER released.
    4. Sets signal_map[session_state.session_id] = True so server.py can issue
       the <Dial> XML redirect when Vobiz fetches /transfer-emergency/{call_id}.
    5. Calls params.result_callback({"success": True, "transfer_initiated": True}).

    Args:
        session_state: Per-call state. Mutable; handler reads token_held / token_confirmed.
        redis_client: Async Redis client (aioredis). Must support await r.decr(key).
        signal_map: Module-level dict in agent/server.py. Handler mutates it by reference.
        audit_writer: Callable matching backend.services.audit_service.write_audit_row
                      signature (keyword-only). Injected for testability.
        branch_emergency_contact: Full E.164 emergency number. NEVER logged in full;
                                  only last 4 digits appear in audit metadata.
        tts_say: Async callable (str) -> None. Injected for testability. In production
                 this is wired to the Pipecat TTS output (e.g. pipeline push or session.say).
    """
    _log = structlog.get_logger()

    async def _handler(params: Any) -> None:
        reason: str = params.arguments.get("reason", "unknown")

        # 1. Speak brief Telugu confirmation. CLAUDE.md RULE 6: sanitize_for_tts() always.
        tts_text = sanitize_for_tts("Sare, miru clinic ki connect chestunnanu.")
        await tts_say(tts_text)

        # 2. Write audit row. PII denylist: only last 4 of emergency contact in metadata.
        #    Audit failure is never fatal — catch, log, continue.
        contact_last4 = branch_emergency_contact[-4:] if branch_emergency_contact else "unknown"
        try:
            await audit_writer(
                action="human_transfer_requested",
                resource_type="call",
                resource_id=session_state.session_id,
                branch_id=session_state.branch_id,
                ip_address=None,
                user_agent="voice-agent/pipecat",
                metadata={
                    "reason": reason,
                    "branch_emergency_contact_last4": contact_last4,
                },
            )
        except Exception as audit_exc:
            _log.error(
                "audit_write_failed_human_transfer",
                error=str(audit_exc),
                session_id=session_state.session_id,
            )

        # 3. Release held-unconfirmed token via Redis DECR. CLAUDE.md RULE 3.
        #    Confirmed tokens are NEVER released — DECR is rollback-only.
        if (
            session_state.token_held
            and not session_state.token_confirmed
            and session_state.token_redis_key
        ):
            await redis_client.decr(session_state.token_redis_key)
            _log.warning(
                "token_released_on_human_transfer",
                token=session_state.token_number,
                session_id=session_state.session_id,
            )

        # 4. Set per-call transfer signal. agent/server.py reads this on /transfer-emergency.
        if session_state.session_id:
            signal_map[session_state.session_id] = True

        _log.info(
            "human_transfer_initiated",
            session_id=session_state.session_id,
            reason=reason,
            branch_id=str(session_state.branch_id) if session_state.branch_id else "unknown",
        )

        # 5. Return result to LLM — stops further generation on this turn.
        await params.result_callback({"success": True, "transfer_initiated": True})

    return _handler


def register_tools(
    llm: Any,
    session_state: SessionState,
    db_session: Any,
    redis_client: Any = None,
    calendar_service: Any = None,
    meta_service: Any = None,
    signal_map: dict[str, bool] | None = None,
    branch_emergency_contact: str = "",
    tts_say: Callable[[str], Any] | None = None,
    **kwargs: Any,
) -> None:
    """Register all 5 LLM function tools on the LLM service.

    Wires FunctionSchema definitions to async handler closures via
    llm.register_function(name, handler). Each booking tool delegates to the
    matching function in agent/tools/booking_tools.py with injected dependencies.
    The request_human_transfer tool uses make_request_human_transfer_handler().

    booking_tools.py is frozen (Task 7 only registers; no modification to that file).

    Args:
        llm: LLM service (GeminiFallbackLLMService or compatible). Must expose
             register_function(name, handler).
        session_state: Per-call SessionState dataclass (mutable, shared by handlers).
        db_session: AsyncSession for DB queries inside tool handlers.
        redis_client: Async Redis client. Passed to assign_token + transfer handler.
        calendar_service: CalendarService instance (stub or real).
        meta_service: MetaService instance (stub or real).
        signal_map: dict[session_id, bool] from agent/server.py. Transfer handler writes it.
        branch_emergency_contact: Full E.164 string. Only last 4 logged in audits.
        tts_say: Async callable for speaking TTS in the transfer handler.
        **kwargs: Additional keyword args accepted for forward-compatibility.
    """
    import asyncio
    from datetime import date, time as dtime
    from uuid import UUID

    from agent.tools.booking_tools import (
        route_to_doctor as _route_to_doctor,
        check_availability as _check_availability,
        assign_token as _assign_token,
        confirm_booking as _confirm_booking,
    )

    if signal_map is None:
        signal_map = {}
    if tts_say is None:
        async def _noop_tts(text: str) -> None:
            pass
        tts_say = _noop_tts

    # ── route_to_doctor ──────────────────────────────────────────────────────
    async def _handle_route_to_doctor(params: Any) -> None:
        args = params.arguments
        complaint: str = args["complaint"]

        # llm_call closure: adapts LLM inference for booking_tools routing logic.
        # booking_tools.route_to_doctor uses this to pick the best-fit doctor
        # when there are multiple doctors and no clear keyword match.
        async def llm_call(messages: list[dict[str, str]]) -> str:
            # For multi-doctor routing we use the fallback chain directly via
            # the configured LLM service. GoogleLLMService does not expose a
            # simple chat-completion API; we call google.genai directly here.
            # If that fails, the outer route_to_doctor fallback already handles
            # it by returning the default doctor.
            try:
                import asyncio as _aio
                import google.genai as genai  # type: ignore[import]
                client = genai.Client(api_key=settings.gemini_api_key)
                combined = "\n".join(m["content"] for m in messages)
                resp = await _aio.to_thread(
                    client.models.generate_content,
                    model="gemini-2.5-flash",
                    contents=combined,
                )
                return resp.text
            except Exception as exc:
                logger.error("llm_call_for_routing_failed", error=str(exc))
                # Fallback to OpenAI for routing
                from openai import AsyncOpenAI
                oai = AsyncOpenAI(api_key=settings.openai_api_key)
                resp = await oai.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=messages,
                    temperature=0,
                )
                return resp.choices[0].message.content or ""

        result = await _route_to_doctor(
            complaint=complaint,
            branch_id=session_state.branch_id,
            db=db_session,
            llm_call=llm_call,
        )
        await params.result_callback(result)

    # ── check_availability ───────────────────────────────────────────────────
    async def _handle_check_availability(params: Any) -> None:
        args = params.arguments
        doctor_id = UUID(args["doctor_id"])
        booking_date = date.fromisoformat(args["booking_date"])
        query_start: dtime | None = None
        query_end: dtime | None = None
        if args.get("query_start"):
            query_start = dtime.fromisoformat(args["query_start"])
        if args.get("query_end"):
            query_end = dtime.fromisoformat(args["query_end"])

        result = await _check_availability(
            doctor_id=doctor_id,
            branch_id=session_state.branch_id,
            booking_date=booking_date,
            db=db_session,
            query_start=query_start,
            query_end=query_end,
        )
        await params.result_callback({"availability": result})

    # ── assign_token ─────────────────────────────────────────────────────────
    async def _handle_assign_token(params: Any) -> None:
        args = params.arguments
        doctor_id = UUID(args["doctor_id"])
        booking_date = date.fromisoformat(args["booking_date"])
        appointment_time: dtime | None = None
        if args.get("appointment_time"):
            appointment_time = dtime.fromisoformat(args["appointment_time"])

        result = await _assign_token(
            doctor_id=doctor_id,
            branch_id=session_state.branch_id,
            booking_date=booking_date,
            db=db_session,
            appointment_time=appointment_time,
        )
        # Update session state so disconnect handler can release token if needed
        if result.get("success"):
            session_state.token_held = True
            session_state.token_number = result["token_number"]
            session_state.token_redis_key = result["redis_key"]
        await params.result_callback(result)

    # ── confirm_booking ──────────────────────────────────────────────────────
    async def _handle_confirm_booking(params: Any) -> None:
        args = params.arguments
        doctor_id = UUID(args["doctor_id"])
        booking_date = date.fromisoformat(args["booking_date"])
        appointment_time: dtime | None = None
        if args.get("appointment_time"):
            appointment_time = dtime.fromisoformat(args["appointment_time"])

        result = await _confirm_booking(
            doctor_id=doctor_id,
            branch_id=session_state.branch_id,
            patient_name=args["patient_name"],
            patient_phone=args.get("patient_phone"),
            complaint=args["complaint"],
            booking_date=booking_date,
            token_number=int(args["token_number"]),
            followup_consent=bool(args["followup_consent"]),
            appointment_time=appointment_time,
            source="voice",
            db=db_session,
            calendar_service=calendar_service,
            meta_service=meta_service,
        )
        # On success, mark token confirmed so disconnect won't roll it back
        if result.get("success"):
            session_state.token_confirmed = True
        await params.result_callback(result)

    # ── request_human_transfer ────────────────────────────────────────────────
    _transfer_handler = make_request_human_transfer_handler(
        session_state=session_state,
        redis_client=redis_client,
        signal_map=signal_map,
        audit_writer=_get_audit_writer(),
        branch_emergency_contact=branch_emergency_contact,
        tts_say=tts_say,
    )

    # Wire all schemas → handlers via FunctionSchema + register_function
    schemas = build_function_schemas()
    handlers: dict[str, Any] = {
        "route_to_doctor": _handle_route_to_doctor,
        "check_availability": _handle_check_availability,
        "assign_token": _handle_assign_token,
        "confirm_booking": _handle_confirm_booking,
        "request_human_transfer": _transfer_handler,
    }

    for schema in schemas:
        llm.register_function(schema.name, handlers[schema.name])

    logger.info(
        "tools_registered",
        tools=[s.name for s in schemas],
        session_id=session_state.session_id,
    )


def _get_audit_writer() -> Callable[..., Any]:
    """Return the audit_service write_audit_row callable.

    Isolated into a helper so register_tools callers can override it in tests
    by passing audit_writer directly to make_request_human_transfer_handler.
    Production code uses the real DB-backed writer.
    """
    from backend.services.audit_service import write_audit_row
    return write_audit_row


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

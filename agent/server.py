"""
agent/server.py — Vachanam FastAPI server for Vobiz webhook + WebSocket voice pipeline.

Endpoints:
  GET  /health                       — liveness probe (no DB, no Redis required)
  POST /answer                       — Vobiz webhook; returns XML with <Speak>, <Stream>, <Record>
  WS   /ws                           — WebSocket; handed off to bot.py in Task 9
  POST /start                        — outbound trigger (Task 10)
  POST /recording-finished           — Vobiz recording callback (Task 10)
  POST /recording-ready              — Vobiz MP3 URL callback (Task 10)
  GET  /transfer-emergency/{call_id} — mid-call transfer XML (Task 8)
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, Optional
from xml.sax.saxutils import escape

import aiohttp
import structlog
import redis.asyncio as aioredis
from fastapi import FastAPI, Form, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from sqlalchemy import select

import agent.bot as bot
import backend.config as _cfg
from backend.database import AsyncSessionLocal
from backend.models.schema import Branch

# ─── Recordings directory (module-level so tests can monkeypatch it) ──────────
_RECORDINGS_DIR: Path = Path("agent/recordings")

# ─── Allowed characters in CallSid from Vobiz (path-traversal guard) ─────────
_CALL_SID_RE = re.compile(r"^[A-Za-z0-9_-]+$")

logger = structlog.get_logger()

app = FastAPI(title="Vachanam Voice Agent", version="0.1.0")

# ─── Transfer signal map ───────────────────────────────────────────────────────
# Set by agent/bot.py:make_request_human_transfer_handler when the LLM tool fires.
# Cleared (popped) by the /transfer-emergency/{call_id} route on successful read.
# Keyed by call_id (str). Value is always True when present.
_transfer_signals: dict[str, bool] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_ws_url(public_url: str) -> str:
    """
    Convert PUBLIC_URL to a bare WebSocket URL (no query params).

    Vobiz does NOT read caller identity from the WS URL query string.
    Caller info (call_uuid, dialed DID, caller phone) arrives in the first
    WebSocket message (Vobiz "start event"), parsed by
    pipecat.serializers.vobiz inside bot.run_pipeline.

    https://agent-dev.vachanam.in  →  wss://agent-dev.vachanam.in/ws
    http://localhost:7860           →  ws://localhost:7860/ws
    """
    base = public_url.rstrip("/")
    if base.startswith("https://"):
        ws_base = base.replace("https://", "wss://", 1)
    elif base.startswith("http://"):
        ws_base = base.replace("http://", "ws://", 1)
    else:
        # No scheme — default to ws:// (dev fallback)
        ws_base = f"ws://{base}"

    return f"{ws_base}/ws"


def _build_answer_xml(
    public_url: str,
    recording_enabled: bool,
    speak_text: str,
) -> str:
    """
    Build the Vobiz XML response for /answer (inbound path).

    speak_text must already be XML-escaped by the caller (use escape() from
    xml.sax.saxutils). This keeps the builder pure / testable.

    Stream tag uses bare WS URL — no query params. Caller identity arrives in
    the Vobiz start event (first WebSocket message), not in the URL.

    Vobiz-specific Stream attributes (from official Vobiz-X-Pipecat reference):
      audioTrack="inbound"    — stream the inbound audio channel
      keepCallAlive="true"    — keep the call alive while the WebSocket is open

    Record tag uses Vobiz attribute naming:
      callbackUrl    — NOT Twilio's "action"
      callbackMethod — POST
      fileFormat     — wav (Vobiz reference uses wav, not mp3)
    """
    ws_url = _build_ws_url(public_url)

    record_block = ""
    if recording_enabled:
        callback_url = f"{public_url.rstrip('/')}/recording-ready"
        record_block = (
            f'\n  <Record callbackUrl="{escape(callback_url)}" callbackMethod="POST"'
            f' recordSession="true" maxLength="3600" fileFormat="wav"/>'
        )

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<Response>\n"
        f'  <Speak voice="WOMAN" language="te-IN">{speak_text}</Speak>\n'
        f'  <Stream bidirectional="true" audioTrack="inbound" contentType="audio/x-mulaw;rate=8000"'
        f' keepCallAlive="true">{escape(ws_url)}</Stream>'
        f"{record_block}\n"
        "</Response>"
    )
    return xml


def _build_outbound_answer_xml(public_url: str) -> str:
    """
    Build the Vobiz XML response for /answer when Direction=outbound.

    Differences from the inbound XML:
      - NO <Speak> tag — patient was dialed by us; AI will speak first turn
        through the WebSocket, no pre-WebSocket greeting needed.
      - Matches reference Vobiz-X-Pipecat server.py exactly:
        <Record> precedes <Stream>; both required to keep Vobiz in webhook flow.
      - audioTrack="inbound" — Vobiz only accepts "inbound"/"outbound".
        bidirectional="true" handles the return audio path.

    Same /ws endpoint; Pipecat/bot.py handles the session identically.
    """
    ws_url = _build_ws_url(public_url)
    recording_callback = f"{public_url.rstrip('/')}/recording-ready"

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<Response>\n"
        f'  <Record fileFormat="wav" maxLength="3600" recordSession="true"'
        f' callbackUrl="{escape(recording_callback)}" callbackMethod="POST"></Record>\n'
        f'  <Stream bidirectional="true" audioTrack="inbound" contentType="audio/x-mulaw;rate=8000"'
        f' keepCallAlive="true">{escape(ws_url)}</Stream>\n'
        "</Response>"
    )
    return xml


# ---------------------------------------------------------------------------
# Branch name resolver (for /answer DID greeting)
# ---------------------------------------------------------------------------


async def resolve_branch_name_for_did(did: str) -> str | None:
    """Look up Branch.name for the dialed DID number.

    Opens a fresh AsyncSession per call (never reuses a module-level session).
    Follows CLAUDE.md RULE 5: branch identity comes from the dialed DID, never
    from the caller phone.

    Returns the branch name string, or None if:
      - No branch row matches the DID.
      - Any DB exception occurs (caller must handle gracefully).

    PII policy: full DID is NEVER logged; only did_last4.
    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Branch).where(Branch.did_number == did)
        )
        branch = result.scalar_one_or_none()

    if branch is None:
        return None

    # Capture attribute value before session closes (CLAUDE.md RULE 8 /
    # DetachedInstanceError guard).
    name: str = branch.name
    return name


# ---------------------------------------------------------------------------
# Branch emergency-contact resolver
# ---------------------------------------------------------------------------


async def resolve_branch_emergency_contact(call_id: str) -> str | None:
    """Look up branch.emergency_contact for a given call_id.

    Uses the call_id → DID mapping maintained by agent/bot.py:run_pipeline
    (written on pipeline entry, deleted on exit). Then opens a fresh DB session
    to query the Branch row by did_number.

    Opens + closes its own AsyncSession (this runs in an HTTP request context,
    not the WebSocket pipeline context). Follows CLAUDE.md RULE 5: branch
    identity comes from dialed DID, never from caller phone.

    Returns emergency_contact string or None if call_id is unknown / DID not
    mapped to a branch / branch has no emergency_contact configured.

    PII policy: emergency_contact full number is NEVER logged. Only last-4 is
    recorded in any structlog event emitted here.
    """
    # Import here to avoid circular import at module load time
    from agent.bot import _call_id_to_did

    did = _call_id_to_did.get(call_id)
    if not did:
        logger.warning(
            "resolve_branch_no_did_mapping",
            call_id=call_id,
        )
        return None

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Branch).where(Branch.did_number == did)
        )
        branch = result.scalar_one_or_none()

    if branch is None:
        logger.warning(
            "resolve_branch_unknown_did",
            did_last4=did[-4:] if did else "unknown",
        )
        return None

    contact = branch.emergency_contact
    if not contact:
        logger.warning(
            "resolve_branch_no_emergency_contact",
            branch_id=str(branch.id),
        )
        return None

    logger.info(
        "resolve_branch_emergency_contact_found",
        branch_id=str(branch.id),
        contact_last4=contact[-4:],
    )
    return contact


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict:
    """
    Liveness probe. Must return 200 without any external dependency.
    Used by Fly.io health checks and UptimeRobot.
    """
    return {"status": "ok"}


@app.api_route("/answer", methods=["GET", "POST"])
async def answer(
    request: Request,
    CallUUID: str | None = Query(None),
    body_data: str | None = Query(None),
) -> Response:
    """
    Vobiz webhook — called on both inbound call pickup and outbound call answer.

    Accepts both GET and POST (Vobiz may use either depending on app config).
    Caller identity is NOT available here — Vobiz does NOT send Twilio-style
    From/To/CallSid Form fields. The call UUID is passed as the `CallUUID`
    query param. An optional `body_data` query param carries base64-encoded JSON
    (Vobiz extended payload — parsed if needed in future).

    Direction detection (form body field "Direction", capital-D per Vobiz docs):
      - "outbound" (case-insensitive) → outbound XML: no <Speak>, audioTrack="both",
        no <Record>. AI speaks first turn through the WebSocket.
      - absent / any other value        → inbound XML (existing path, unchanged).

    Branch resolution: uses settings.vobiz_did_number (env var = the
    platform-owned DID for this agent instance). Single-DID dev model.
    Multi-clinic at scale: TD-039 (1 Voice App per DID, look up by app ID).

    Returns XML with appropriate tags.
    This endpoint MUST NEVER return 5xx — Vobiz needs XML or the call drops.
    All branch lookup + body parsing is wrapped in try/except (guardrail 1).

    Privacy: full DID is never logged; only did_last4.
    """
    # Read settings fresh per request (not at module import time) so that
    # monkeypatch in tests can override them reliably.
    recording_enabled: bool = _cfg.settings.recording_allowed
    public_url: str = _cfg.settings.public_url

    # ── Detect call direction from form body ──────────────────────────────────
    # Vobiz POSTs form-urlencoded data; GET requests have no body.
    # If the field is absent (e.g. a GET health-poll or older Vobiz firmware),
    # default to inbound so existing behavior is preserved.
    direction: str = ""
    if request.method == "POST":
        try:
            form = await request.form()
            direction = (form.get("Direction") or "").strip()
        except Exception:
            direction = ""

    is_outbound: bool = direction.lower() == "outbound"

    logger.info(
        "answer_received",
        call_uuid=CallUUID,
        method=request.method,
        recording_enabled=recording_enabled,
        direction=direction or "not_set",
        is_outbound=is_outbound,
    )

    # ── Outbound path ─────────────────────────────────────────────────────────
    # No greeting needed — we placed the call; AI speaks first via WebSocket.
    if is_outbound:
        xml_body = _build_outbound_answer_xml(public_url=public_url)
        logger.info(
            "answer_direction",
            direction=direction,
            call_uuid=CallUUID,
            is_outbound=True,
        )
        return Response(content=xml_body, media_type="application/xml")

    # ── Inbound path (original logic, unchanged) ──────────────────────────────
    logger.info(
        "answer_direction",
        direction=direction or "not_set",
        call_uuid=CallUUID,
        is_outbound=False,
    )

    # Resolve clinic name for personalised greeting.
    # Branch comes from the DID configured in settings (CLAUDE.md RULE 7 /
    # agent-persona-doc RULE 7: branch context from room metadata or env, never
    # inferred from caller phone).
    # Single-DID dev: settings.vobiz_did_number is authoritative.
    # TD-039: at multi-clinic scale, switch to 1-app-per-DID + look up by
    # Vobiz app_id so each DID maps to its own agent instance.
    # Wrapped in try/except — DB error must NEVER 500 this endpoint.
    _VACHANAM_FALLBACK = "నమస్కారం, Vachanam కి స్వాగతం"
    clinic_did: str = _cfg.settings.vobiz_did_number
    did_last4: str = clinic_did[-4:] if clinic_did else "????"
    try:
        clinic_name: str | None = await resolve_branch_name_for_did(clinic_did)
    except Exception as exc:
        logger.warning(
            "answer_branch_lookup_failed",
            did_last4=did_last4,
            error=str(exc),
        )
        clinic_name = None

    if clinic_name:
        speak_text = escape(f"నమస్కారం, {clinic_name} కి స్వాగతం")
        logger.info(
            "answer_branch_resolved",
            did_last4=did_last4,
            clinic_name=clinic_name,
        )
    else:
        speak_text = escape(_VACHANAM_FALLBACK)
        logger.warning("answer_branch_not_found_using_saas_brand", did_last4=did_last4)

    xml_body = _build_answer_xml(
        public_url=public_url,
        recording_enabled=recording_enabled,
        speak_text=speak_text,
    )

    return Response(content=xml_body, media_type="application/xml")


# ---------------------------------------------------------------------------
# Stub routes — filled in by later tasks
# ---------------------------------------------------------------------------

@app.websocket("/ws")
async def websocket_ws(websocket: WebSocket) -> None:
    """WebSocket endpoint. Vobiz connects here after /answer returns <Stream>.

    Vobiz does NOT put call identity in the WebSocket URL query string.
    Caller info (call_uuid, dialed DID, caller phone) arrives in the FIRST
    WebSocket message (the Vobiz "start event"), parsed by
    pipecat.serializers.vobiz.parse_vobiz_start inside bot.run_pipeline.

    This handler:
      1. Accepts the WebSocket unconditionally — no 400 on missing params.
      2. Opens a per-connection Redis client.
      3. Delegates to bot.run_pipeline(websocket, redis_client).
         run_pipeline calls parse_vobiz_start internally to extract call_id/DID.
      4. finally: close Redis, close WebSocket (idempotent).

    Exception handling:
      - WebSocketDisconnect from clean caller hangup → INFO log, not ERROR.
      - All other exceptions → ERROR log; never re-raised (guardrail 2:
        /ws must never raise out of the handler — uvicorn worker must survive).

    Privacy: only last 4 digits of DID logged in all structlog events here.
    """
    # ── 1. Accept WebSocket unconditionally ──────────────────────────────────
    # Caller identity (call_uuid, to, from) arrives in the Vobiz start event
    # (first WS message) — NOT in the URL. Rejecting here would drop the call.
    await websocket.accept()

    logger.info("ws_connected")

    # ── 2. Open per-connection Redis client ───────────────────────────────────
    # One client per WebSocket connection — never module-level (event-loop safety).
    redis_client = aioredis.from_url(
        _cfg.settings.redis_url,
        decode_responses=True,
    )

    # ── 3. Run pipeline; catch all exceptions so uvicorn worker survives ──────
    try:
        await bot.run_pipeline(
            websocket=websocket,
            redis_client=redis_client,
        )
    except WebSocketDisconnect:
        # Clean caller hangup — not an error condition.
        logger.info("ws_disconnected_cleanly")
    except Exception as exc:
        # Unexpected pipeline error — log as ERROR but do NOT re-raise.
        # Re-raising would kill the uvicorn worker; other concurrent calls
        # must continue running.
        logger.error("ws_disconnected_with_exception", error=str(exc))
    finally:
        # ── 4. Cleanup — always runs regardless of exception path ─────────────
        # Close Redis client — mandatory to avoid connection leaks.
        # aioredis.aclose() is the canonical async close.
        try:
            await redis_client.aclose()
        except Exception as redis_close_exc:
            logger.warning("ws_redis_close_failed", error=str(redis_close_exc))

        # Close WebSocket — idempotent if Pipecat or Vobiz already closed it.
        try:
            await websocket.close()
        except Exception:
            pass  # Already closed — safe to ignore

        logger.info("ws_cleanup_complete")


@app.post("/recording-finished")
async def recording_finished(
    CallSid: Annotated[str, Form()] = "",
    duration: Annotated[Optional[str], Form()] = None,
) -> JSONResponse:
    """
    Vobiz callback (POST form) when a recording stream finishes.

    Always returns 200 so Vobiz does not retry — even when RECORDING_ENABLED
    is false (guardrail: gate the business logic, never the HTTP response).

    Logs a structured event `recording_finished` with:
      - call_sid    — the Vobiz call identifier
      - duration_seconds — parsed int if present, else None
      - recording_enabled — current setting value

    Privacy: CallSid is opaque and safe to log in full; no phone numbers here.
    """
    recording_enabled: bool = _cfg.settings.recording_allowed
    duration_seconds: Optional[int] = None
    if duration is not None:
        try:
            duration_seconds = int(duration)
        except ValueError:
            pass  # non-numeric duration — log None, don't crash

    logger.info(
        "recording_finished",
        call_sid=CallSid,
        duration_seconds=duration_seconds,
        recording_enabled=recording_enabled,
    )

    if not recording_enabled:
        logger.warning(
            "recording_finished_ignored_recording_disabled",
            call_sid=CallSid,
        )

    return JSONResponse({"ok": True})


@app.post("/recording-ready")
async def recording_ready(
    CallSid: Annotated[str, Form()] = "",
    recording_url: Annotated[str, Form()] = "",
) -> JSONResponse:
    """
    Vobiz callback (POST form) with the MP3 download URL.

    Accept form params — Vobiz follows the Twilio-style webhook pattern
    (application/x-www-form-urlencoded). If a real call in Task 14 smoke
    reveals JSON instead, switch `Form()` to `Body()` for those two fields.

    Path-traversal protection: CallSid is validated against ^[A-Za-z0-9_-]+$
    before being used in the filesystem path. Invalid CallSid → 400.

    When RECORDING_ENABLED=false: log warning and return 200 immediately;
    no download attempted (guardrail: always 200 to Vobiz).

    On aiohttp error: log `recording_download_failed` (URL masked) + return
    200 (download is best-effort; Vobiz must not retry for a local-save issue).

    Vobiz auth headers are sent but NEVER logged (auth_id only, not token).
    """
    recording_enabled: bool = _cfg.settings.recording_allowed

    # ── Guard: path traversal — validate CallSid before any filesystem use ──
    if not CallSid or not _CALL_SID_RE.match(CallSid):
        logger.warning(
            "recording_ready_invalid_call_sid",
            call_sid_raw=CallSid[:40],  # truncate any huge input
        )
        raise HTTPException(status_code=400, detail="invalid_call_sid")

    if not recording_enabled:
        logger.warning(
            "recording_ready_skipped_recording_disabled",
            call_sid=CallSid,
        )
        return JSONResponse({"ok": True})

    auth_id: str = _cfg.settings.vobiz_auth_id
    auth_token: str = _cfg.settings.vobiz_auth_token

    # Log auth_id (public-ish identifier) but NEVER auth_token (guardrail 4).
    logger.info(
        "recording_ready_download_start",
        call_sid=CallSid,
        auth_id=auth_id,
        # recording_url intentionally omitted — may contain signed tokens
    )

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                recording_url,
                headers={
                    "X-Auth-ID": auth_id,
                    "X-Auth-Token": auth_token,
                },
            ) as resp:
                resp.raise_for_status()
                content: bytes = await resp.read()

        dest: Path = _RECORDINGS_DIR / f"{CallSid}.mp3"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)

        logger.info(
            "recording_downloaded",
            call_sid=CallSid,
            size_bytes=len(content),
            path=str(dest),
        )
    except Exception as exc:
        # Best-effort download — log but never let Vobiz retry for a local save failure.
        logger.error(
            "recording_download_failed",
            call_sid=CallSid,
            # URL masked — may contain signed auth tokens in query string
            error=str(exc),
        )

    return JSONResponse({"ok": True})


class _StartRequest(BaseModel):
    """Outbound call trigger request body."""

    to: str


@app.post("/start")
async def start(body: _StartRequest) -> JSONResponse:
    """
    Outbound call trigger (POST JSON).

    Validates `to` is a non-empty E.164 number (starts with '+', digits only
    after). Rejects with 400 otherwise (guardrail 5).

    POSTs to Vobiz Partner API:
      POST https://api.vobiz.ai/api/v1/Account/{auth_id}/Call/
      Headers: X-Auth-ID, X-Auth-Token
      Body:
        from        — settings.vobiz_did_number
        to          — caller-supplied destination
        answer_url  — {settings.public_url}/answer
        answer_method — POST

    Returns the upstream Vobiz JSON response body verbatim.

    TODO: Add per-minute outbound rate limiting via slowapi (TD-037).
    Privacy: `to` is logged as last-4 digits only.
    Auth: NEVER log X-Auth-Token (guardrail 4); only auth_id is logged.
    """
    to: str = body.to

    # ── E.164 validation: must start with '+' and have only digits after ──────
    if not to or not to.startswith("+") or not re.fullmatch(r"\+[0-9]+", to):
        logger.warning("start_invalid_e164", to_last4=to[-4:] if to else "")
        raise HTTPException(status_code=400, detail="invalid_e164_number")

    auth_id: str = _cfg.settings.vobiz_auth_id
    auth_token: str = _cfg.settings.vobiz_auth_token
    from_number: str = _cfg.settings.vobiz_did_number
    public_url: str = _cfg.settings.public_url.rstrip("/")
    answer_url: str = f"{public_url}/answer"

    vobiz_url = f"https://api.vobiz.ai/api/v1/Account/{auth_id}/Call/"

    logger.info(
        "outbound_call_start",
        to_last4=to[-4:],
        from_last4=from_number[-4:] if from_number else "",
        auth_id=auth_id,
        # auth_token NEVER logged
    )

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                vobiz_url,
                headers={
                    "X-Auth-ID": auth_id,
                    "X-Auth-Token": auth_token,
                    "Content-Type": "application/json",
                },
                json={
                    "from": from_number,
                    "to": to,
                    "answer_url": answer_url,
                    "answer_method": "POST",
                },
            ) as resp:
                status = resp.status
                vobiz_data: dict = await resp.json()
        if status >= 400:
            logger.warning(
                "vobiz_outbound_call_rejected",
                status=status,
                to_last4=to[-4:],
            )
            raise HTTPException(
                status_code=502,
                detail=f"vobiz_upstream_status_{status}",
            )
        logger.info(
            "vobiz_outbound_call_accepted",
            status=status,
            to_last4=to[-4:],
            call_id=vobiz_data.get("call_id", "unknown"),
        )
        return JSONResponse(content=vobiz_data, status_code=status)
    except aiohttp.ClientError as e:
        logger.error(
            "vobiz_outbound_call_network_error",
            error=str(e),
            to_last4=to[-4:],
        )
        raise HTTPException(
            status_code=502,
            detail="vobiz_unreachable",
        ) from e


@app.get("/transfer-emergency/{call_id}")
async def transfer_emergency(call_id: str) -> Response:
    """
    Vobiz fetches this when request_human_transfer LLM tool fires for a call.
    Returns <Dial> XML pointing at branch.emergency_contact. 404 when no signal
    or branch is unresolvable. The signal is popped on read (single-use).
    """
    if not _transfer_signals.pop(call_id, False):
        logger.info("transfer_emergency_no_signal", call_id=call_id)
        raise HTTPException(status_code=404, detail="no transfer signal for call_id")

    emergency_contact = await resolve_branch_emergency_contact(call_id)
    if not emergency_contact:
        logger.warning("transfer_emergency_unresolved", call_id=call_id)
        raise HTTPException(status_code=404, detail="branch not resolvable for call_id")

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Response>\n'
        f'  <Dial>{escape(emergency_contact)}</Dial>\n'
        '</Response>'
    )
    logger.info("transfer_emergency_dial_returned", call_id=call_id, contact_last4=emergency_contact[-4:])
    return Response(content=xml, media_type="application/xml")

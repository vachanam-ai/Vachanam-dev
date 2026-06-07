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

import urllib.parse
from typing import Annotated
from xml.sax.saxutils import escape

import structlog
import redis.asyncio as aioredis
from fastapi import FastAPI, Form, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select

import agent.bot as bot
import backend.config as _cfg
from backend.database import AsyncSessionLocal
from backend.models.schema import Branch

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

def _build_ws_url(public_url: str, call_sid: str, caller: str, did: str) -> str:
    """
    Convert PUBLIC_URL to a WebSocket URL and append query params.

    https://agent-dev.vachanam.in  →  wss://agent-dev.vachanam.in/ws?...
    http://localhost:7860           →  ws://localhost:7860/ws?...
    """
    base = public_url.rstrip("/")
    if base.startswith("https://"):
        ws_base = base.replace("https://", "wss://", 1)
    elif base.startswith("http://"):
        ws_base = base.replace("http://", "ws://", 1)
    else:
        # No scheme — default to ws:// (dev fallback)
        ws_base = f"ws://{base}"

    encoded_caller = urllib.parse.quote_plus(caller)
    encoded_did = urllib.parse.quote_plus(did)
    return (
        f"{ws_base}/ws"
        f"?call_id={urllib.parse.quote_plus(call_sid)}"
        f"&to={encoded_did}"
        f"&from={encoded_caller}"
    )


def _build_answer_xml(
    caller: str,
    did: str,
    call_sid: str,
    public_url: str,
    recording_enabled: bool,
) -> str:
    """
    Build the Vobiz TwiML-compatible XML response for POST /answer.
    All string args are already validated by FastAPI Form parsing.
    """
    ws_url = _build_ws_url(public_url, call_sid, caller, did)

    record_block = ""
    if recording_enabled:
        record_action = f"{public_url.rstrip('/')}/recording-finished"
        record_block = (
            f'\n  <Record action="{escape(record_action)}" recordSession="true"'
            f' maxLength="3600" fileFormat="mp3"/>'
        )

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<Response>\n"
        '  <Speak voice="WOMAN" language="te-IN">Hello</Speak>\n'
        f'  <Stream bidirectional="true" contentType="audio/x-mulaw;rate=8000">{escape(ws_url)}</Stream>'
        f"{record_block}\n"
        "</Response>"
    )
    return xml


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


@app.post("/answer")
async def answer(
    From: Annotated[str, Form()],
    To: Annotated[str, Form()],
    CallSid: Annotated[str, Form()],
) -> Response:
    """
    Vobiz calls this URL (POST, application/x-www-form-urlencoded) when a call arrives.
    Returns XML telling Vobiz to speak a greeting, open a bidirectional WebSocket stream,
    and optionally record the session.

    Privacy: only the last 4 digits of From/To are logged.
    """
    # Read settings fresh per request (not at module import time) so that
    # monkeypatch in tests can override them reliably.
    recording_enabled: bool = _cfg.settings.recording_enabled
    public_url: str = _cfg.settings.public_url

    logger.info(
        "answer_received",
        caller_last4=From[-4:],
        did_last4=To[-4:],
        call_sid=CallSid,
        recording_enabled=recording_enabled,
    )

    xml_body = _build_answer_xml(
        caller=From,
        did=To,
        call_sid=CallSid,
        public_url=public_url,
        recording_enabled=recording_enabled,
    )

    return Response(content=xml_body, media_type="application/xml")


# ---------------------------------------------------------------------------
# Stub routes — filled in by later tasks
# ---------------------------------------------------------------------------

@app.websocket("/ws")
async def websocket_ws(websocket: WebSocket) -> None:
    """WebSocket endpoint. Vobiz connects here after /answer returns <Stream>.

    Query params (all required):
      call_id — Vobiz call identifier (maps to _call_id_to_did and _transfer_signals)
      to      — Dialed DID number (clinic's number). CLAUDE.md RULE 5: branch
                identity comes from DID, NEVER from caller phone.
      from    — Caller's phone number (used only for logging, last 4 digits).

    Lifecycle:
      1. Validate query params — 400 close if any missing.
      2. Accept WebSocket.
      3. Open a per-connection Redis client (aioredis.from_url).
      4. Call bot.run_pipeline(websocket, call_id, did, caller, redis_client).
      5. finally: close Redis, close WebSocket (idempotent).

    Exception handling:
      - WebSocketDisconnect from clean caller hangup → INFO log, not ERROR.
      - All other exceptions → ERROR log before close.
      - Nothing re-raised — uvicorn worker must not crash on call teardown.

    Privacy: only last 4 digits of caller/DID logged in all structlog events.
    """
    # ── 1. Validate required query params ────────────────────────────────────
    params = websocket.query_params
    call_id: str | None = params.get("call_id")
    to: str | None = params.get("to")
    from_: str | None = params.get("from")

    if not call_id or not to or not from_:
        missing = [k for k, v in (("call_id", call_id), ("to", to), ("from", from_)) if not v]
        logger.warning("ws_missing_query_params", missing=missing)
        await websocket.close(code=1008, reason="missing_query_params")
        return

    # ── 2. Accept WebSocket ───────────────────────────────────────────────────
    await websocket.accept()

    logger.info(
        "ws_connected",
        call_id=call_id,
        did_last4=to[-4:],
        caller_last4=from_[-4:],
    )

    # ── 3. Open per-connection Redis client ───────────────────────────────────
    # One client per WebSocket connection — never module-level (event-loop safety).
    # Same pattern as agent/tools/booking_tools.py:_redis (from_url + decode_responses).
    redis_client = aioredis.from_url(
        _cfg.settings.redis_url,
        decode_responses=True,
    )

    # ── 4. Run pipeline; catch all exceptions so uvicorn worker survives ──────
    try:
        await bot.run_pipeline(
            websocket=websocket,
            call_id=call_id,
            did=to,
            caller=from_,
            redis_client=redis_client,
        )
    except WebSocketDisconnect:
        # Clean caller hangup — not an error condition.
        logger.info(
            "ws_disconnected_cleanly",
            call_id=call_id,
            did_last4=to[-4:],
            caller_last4=from_[-4:],
        )
    except Exception as exc:
        # Unexpected pipeline error — log as ERROR but do NOT re-raise.
        # Re-raising would kill the uvicorn worker; other concurrent calls
        # must continue running.
        logger.error(
            "ws_disconnected_with_exception",
            call_id=call_id,
            did_last4=to[-4:],
            caller_last4=from_[-4:],
            error=str(exc),
        )
    finally:
        # ── 5. Cleanup — always runs regardless of exception path ─────────────
        # Clear the transfer signal if the call ended before /transfer-emergency
        # was fetched (avoids stale entries in the module dict for long-running
        # servers across many calls).
        _transfer_signals.pop(call_id, None)

        # Close Redis client — mandatory to avoid connection leaks.
        # aioredis.close() is an alias; aclose() is the canonical async close.
        try:
            await redis_client.aclose()
        except Exception as redis_close_exc:
            logger.warning(
                "ws_redis_close_failed",
                call_id=call_id,
                error=str(redis_close_exc),
            )

        # Close WebSocket — idempotent if Pipecat or Vobiz already closed it.
        try:
            await websocket.close()
        except Exception:
            pass  # Already closed — safe to ignore

        logger.info(
            "ws_cleanup_complete",
            call_id=call_id,
            did_last4=to[-4:],
        )


@app.post("/start")
async def start() -> JSONResponse:
    """Outbound call trigger. Filled in Task 10."""
    return JSONResponse({"error": "not_implemented"}, status_code=501)


@app.post("/recording-finished")
async def recording_finished() -> JSONResponse:
    """Vobiz callback when recording stream ends. Filled in Task 10."""
    return JSONResponse({"error": "not_implemented"}, status_code=501)


@app.post("/recording-ready")
async def recording_ready() -> JSONResponse:
    """Vobiz callback with MP3 download URL. Filled in Task 10."""
    return JSONResponse({"error": "not_implemented"}, status_code=501)


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

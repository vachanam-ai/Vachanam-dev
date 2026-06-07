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
from fastapi import FastAPI, Form, WebSocket
from fastapi.responses import JSONResponse, Response

import backend.config as _cfg

logger = structlog.get_logger()

app = FastAPI(title="Vachanam Voice Agent", version="0.1.0")


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
    """
    WebSocket endpoint. Vobiz connects here after /answer returns <Stream>.
    Full Pipecat pipeline wired in Task 9.
    """
    await websocket.accept()
    await websocket.close(code=1001, reason="not_implemented")


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
async def transfer_emergency(call_id: str) -> JSONResponse:
    """
    Vobiz fetches this when request_human_transfer LLM tool fires for a call.
    Returns <Dial> XML pointing at branch.emergency_contact. Filled in Task 8.
    """
    return JSONResponse({"error": "not_implemented"}, status_code=501)

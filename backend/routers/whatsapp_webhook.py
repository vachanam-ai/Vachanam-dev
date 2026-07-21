"""Meta WhatsApp webhook (spec 2026-07-13, plan T5).

GET  /webhooks/whatsapp — Meta's verify handshake (hub.challenge echo).
POST /webhooks/whatsapp — inbound events, HMAC-verified (X-Hub-Signature-256
over the RAW body with META_APP_SECRET).

Contracts:
- RULE 5: branch = the RECEIVING clinic number (value.metadata.phone_number_id
  → Branch.wa_phone_number_id), never the patient's number. Unknown receiver →
  log + 200 (drop).
- Always 200 after auth — a 5xx makes Meta retry-storm. 403 only for bad
  verify-token / bad signature.
- Idempotent by message id: Redis SETNX wa:msg:{id} TTL 24h (Meta redelivers).
  Shared client via backend.redis_client.get_redis (#305 — never per-call
  TLS clients).
- Handler exceptions → wa_inbound_error log + 200; the patient gets a static
  "please call us" line when a reply address exists (RULE 8, no dead ends).
"""
from __future__ import annotations

import hashlib
import hmac

import structlog
from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.database import get_db
from backend.models.schema import Branch, Organization

logger = structlog.get_logger()

router = APIRouter(prefix="/webhooks", tags=["whatsapp"])

_MSG_TTL = 24 * 3600


@router.get("/whatsapp")
async def verify(
    mode: str = Query(default="", alias="hub.mode"),
    token: str = Query(default="", alias="hub.verify_token"),
    challenge: str = Query(default="", alias="hub.challenge"),
):
    if (
        mode == "subscribe"
        and settings.meta_webhook_verify_token
        and hmac.compare_digest(token, settings.meta_webhook_verify_token)
    ):
        return Response(content=challenge, media_type="text/plain")
    return Response(status_code=403)


def _signature_ok(raw: bytes, header: str | None) -> bool:
    if not settings.meta_app_secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(
        settings.meta_app_secret.encode(), raw, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(header[len("sha256="):], expected)


async def _seen_before(message_id: str) -> bool:
    """SETNX-based dedupe; Redis trouble → treat as unseen (RULE 8 — a lost
    dedupe risks a duplicate reply, never a dropped patient message)."""
    try:
        from backend.redis_client import get_redis

        r = get_redis()
        return not await r.set(f"wa:msg:{message_id}", "1", nx=True, ex=_MSG_TTL)
    except Exception as e:  # noqa: BLE001
        logger.warning("wa_dedupe_unavailable", error=str(e)[:120])
        return False


@router.post("/whatsapp")
async def inbound(request: Request, db: AsyncSession = Depends(get_db)):
    raw = await request.body()
    if not _signature_ok(raw, request.headers.get("X-Hub-Signature-256")):
        logger.warning("wa_webhook_bad_signature")
        return Response(status_code=403)

    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 — malformed body: ack, never retry-storm
        logger.warning("wa_webhook_malformed_body")
        return {"ok": True}

    for entry in body.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            try:
                await _handle_value(db, value)
            except Exception as e:  # noqa: BLE001 — always 200 to Meta
                logger.error("wa_inbound_error", error=str(e)[:300])
    return {"ok": True}


async def _handle_value(db: AsyncSession, value: dict) -> None:
    statuses = value.get("statuses")
    if statuses:
        for st in statuses:
            logger.info(
                "wa_status", status=st.get("status"),
                message_id=st.get("id"),
            )
        return

    messages = value.get("messages")
    if not messages:
        return

    # RULE 5: the branch is the RECEIVING number.
    phone_number_id = (value.get("metadata") or {}).get("phone_number_id")
    row = (
        await db.execute(
            select(Branch, Organization.plan)
            .join(Organization, Organization.id == Branch.org_id)
            .where(Branch.wa_phone_number_id == str(phone_number_id or ""))
        )
    ).first()
    if row is None:
        logger.info("wa_unknown_receiver", phone_number_id=str(phone_number_id))
        return
    branch, plan = row

    from backend.services import wa_actions, wa_chat

    for msg in messages:
        mid = msg.get("id") or ""
        if mid and await _seen_before(mid):
            logger.info("wa_duplicate_dropped", message_id=mid)
            continue
        sender = msg.get("from") or ""  # patient's number, delivery address only
        try:
            if msg.get("type") == "interactive":
                inter = msg.get("interactive") or {}
                reply = inter.get("button_reply") or inter.get("list_reply") or {}
                await wa_actions.dispatch_button(
                    db, branch, plan, sender, reply.get("id") or ""
                )
            elif msg.get("type") == "button":  # template quick-reply payload
                await wa_actions.dispatch_button(
                    db, branch, plan, sender, (msg.get("button") or {}).get("payload") or ""
                )
            elif msg.get("type") == "text":
                await wa_chat.handle_text(
                    db, branch, plan, sender, (msg.get("text") or {}).get("body") or ""
                )
            else:
                logger.info("wa_unsupported_type", mtype=msg.get("type"))
        except Exception as e:  # noqa: BLE001 — never dead-end the patient (RULE 8)
            logger.error("wa_message_error", error=str(e)[:300])
            await wa_actions.reply_call_us(branch, sender, plan)

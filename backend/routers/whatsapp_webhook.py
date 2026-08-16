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
from sqlalchemy import select, update
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
        # entry.id IS the WABA id. Nothing else we receive carries it, and the
        # Graph API will not walk phone_number_id -> WABA, so without this a
        # branch connected by phone number alone has wa_waba_id NULL — and
        # template discovery (which lists /{waba_id}/message_templates) returns
        # nothing, so every template send silently skips. Found 2026-08-05
        # after Vinay got all 7 templates approved and still saw no messages.
        waba_id = str(entry.get("id") or "")
        await _learn_waba_id(db, waba_id, entry.get("changes", []))
        for change in entry.get("changes", []):
            value = change.get("value", {})
            try:
                await _handle_change(db, waba_id, change.get("field") or "", value)
            except Exception as e:  # noqa: BLE001 — always 200 to Meta
                logger.error("wa_inbound_error", error=str(e)[:300])
    return {"ok": True}


async def _learn_waba_id(db: AsyncSession, waba_id, changes: list) -> None:
    """Backfill Branch.wa_waba_id from the webhook that just arrived.

    Best-effort by contract: this runs on the inbound path, so a failure here
    must never cost the patient their reply (RULE 8).
    """
    if not waba_id:
        return
    try:
        pnids = {
            str((c.get("value") or {}).get("metadata", {}).get("phone_number_id") or "")
            for c in changes
        } - {""}
        if not pnids:
            return
        res = await db.execute(
            update(Branch)
            .where(
                Branch.wa_phone_number_id.in_(pnids),
                Branch.wa_status == "connected",
                Branch.wa_waba_id.is_(None),  # never overwrite a known id
            )
            .values(wa_waba_id=str(waba_id))
        )
        if res.rowcount:
            await db.commit()
            logger.info("wa_waba_id_learned", waba_id=str(waba_id), branches=res.rowcount)
            # The cached template map was built while the WABA was unknown
            # (i.e. empty) — drop it so the next send rediscovers.
            from backend.services import wa_template_registry

            for br in (await db.execute(
                select(Branch.id).where(Branch.wa_waba_id == str(waba_id))
            )).scalars().all():
                await wa_template_registry.invalidate(br)
    except Exception as e:  # noqa: BLE001 — never block an inbound message
        logger.warning("wa_waba_learn_failed", error=str(e)[:150])


async def _branch_row(db: AsyncSession, value: dict):
    phone_number_id = (value.get("metadata") or {}).get("phone_number_id")
    return (
        await db.execute(
            select(Branch, Organization.plan)
            .join(Organization, Organization.id == Branch.org_id)
            .where(
                Branch.wa_phone_number_id == str(phone_number_id or ""),
                Branch.wa_status == "connected",
            )
        )
    ).first()


def _set_sync_state(branch: Branch, key: str, status: str, **values) -> None:
    onboarding = dict(branch.wa_onboarding or {})
    sync = dict(onboarding.get("sync") or {})
    item = dict(sync.get(key) or {})
    item.update({"status": status, **values})
    sync[key] = item
    onboarding["sync"] = sync
    branch.wa_onboarding = onboarding


async def _handle_change(
    db: AsyncSession, waba_id: str, field: str, value: dict
) -> None:
    if field == "account_update":
        await _handle_account_update(db, waba_id, value)
        return
    if field == "history" or value.get("history"):
        await _handle_history(db, value)
        return
    if field == "smb_app_state_sync" or value.get("state_sync"):
        row = await _branch_row(db, value)
        if row is None:
            return
        branch, _plan = row
        count = len(value.get("state_sync") or [])
        previous = ((branch.wa_onboarding or {}).get("sync") or {}).get("contacts") or {}
        _set_sync_state(
            branch, "contacts", "receiving",
            received_count=int(previous.get("received_count") or 0) + count,
        )
        await db.commit()
        logger.info("wa_contacts_sync_received", branch_id=str(branch.id), count=count)
        return
    if field == "smb_message_echoes" or value.get("message_echoes"):
        row = await _branch_row(db, value)
        if row is None:
            return
        branch, _plan = row
        from backend.services import wa_session

        count = await wa_session.mirror_echoes(
            db, branch.id, value.get("message_echoes") or []
        )
        await db.commit()
        logger.info("wa_message_echoes_mirrored", branch_id=str(branch.id), count=count)
        return
    await _handle_value(db, value)


async def _handle_history(db: AsyncSession, value: dict) -> None:
    row = await _branch_row(db, value)
    if row is None:
        return
    branch, _plan = row
    blocks = value.get("history") or []
    errors = [error for block in blocks for error in (block.get("errors") or [])]
    if any(int(error.get("code") or 0) == 2593109 for error in errors):
        _set_sync_state(branch, "history", "declined", progress=100)
        await db.commit()
        logger.info("wa_history_sync_declined", branch_id=str(branch.id))
        return

    from backend.services import wa_session

    metadata = value.get("metadata") or {}
    changed = await wa_session.merge_history(
        db,
        branch.id,
        str(metadata.get("display_phone_number") or ""),
        blocks,
    )
    progress = max(
        [int((block.get("metadata") or {}).get("progress") or 0) for block in blocks]
        or [0]
    )
    _set_sync_state(
        branch,
        "history",
        "complete" if progress >= 100 else "receiving",
        progress=progress,
    )
    await db.commit()
    logger.info(
        "wa_history_sync_received",
        branch_id=str(branch.id),
        threads_changed=changed,
        progress=progress,
    )


async def _handle_account_update(db: AsyncSession, waba_id: str, value: dict) -> None:
    event = str(value.get("event") or "")
    if event not in {"PARTNER_REMOVED", "ACCOUNT_OFFBOARDED"}:
        if event == "ACCOUNT_RECONNECTED":
            logger.info("wa_account_reconnected_requires_signup", waba_id=waba_id)
        return
    branch = (
        await db.execute(select(Branch).where(Branch.wa_waba_id == waba_id))
    ).scalar_one_or_none()
    if branch is None:
        return
    from backend.services.wa_lifecycle import disconnect_branch, invalidate_connection_caches

    result = await disconnect_branch(db, branch, status="disconnected")
    await db.commit()
    await invalidate_connection_caches(branch.id)
    logger.warning(
        "wa_account_offboarded",
        branch_id=str(branch.id),
        meta_event=event,
        sessions_purged=result.conversations_deleted,
    )


async def _handle_value(db: AsyncSession, value: dict) -> None:
    for error in value.get("errors") or []:
        logger.info("wa_webhook_error", code=error.get("code"))

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
    row = await _branch_row(db, value)
    if row is None:
        logger.info("wa_unknown_receiver", phone_number_id=str(phone_number_id))
        return
    branch, plan = row

    from backend.services import wa_actions, wa_agent, wa_chat, wa_session

    for msg in messages:
        mid = msg.get("id") or ""
        if mid and await _seen_before(mid):
            logger.info("wa_duplicate_dropped", message_id=mid)
            continue
        sender = msg.get("from") or ""  # patient's number, delivery address only
        try:
            if msg.get("type") in {"edit", "revoke"}:
                await wa_session.apply_edit_or_revoke(
                    db, branch.id, sender, msg
                )
            elif msg.get("type") == "interactive":
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
                # wa_agent (a short prompt + database tools) replaced
                # wa_chat's nine-intent router + canned replies on
                # 2026-08-04 — see wa_agent's module docstring. The old
                # router is kept behind WA_AGENT_TOOLS=false as a one-flag
                # way back if the tool loop misbehaves on a live number.
                if settings.wa_agent_tools:
                    await wa_agent.handle(
                        db, branch, plan, sender, (msg.get("text") or {}).get("body") or ""
                    )
                else:
                    await wa_chat.handle_text(
                        db, branch, plan, sender, (msg.get("text") or {}).get("body") or ""
                    )
            else:
                logger.info("wa_unsupported_type", mtype=msg.get("type"))
        except Exception as e:  # noqa: BLE001 — never dead-end the patient (RULE 8)
            logger.error("wa_message_error", error=str(e)[:300])
            await wa_actions.reply_transient_error(branch, sender, plan)

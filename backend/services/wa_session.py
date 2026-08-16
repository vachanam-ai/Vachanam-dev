"""Per-branch, per-patient WhatsApp conversation state (WA MVP1 Task 3).

Backs onto the EXISTING `whatsapp_sessions` table (`session_data` JSONB
column) — it was dead code until this module, so no migration is needed.
Keyed `(branch_id, patient_phone)`. RULE 1: every query filters by
branch_id so the same phone number at two different clinics can never
share a thread.

`session_data` shape::

    {"turns": [{"role": "patient"|"bot", "text": str, "at": iso8601}, ...],
     "draft": {}}

`turns` is trimmed to the last `WA_SESSION_MAX_TURNS` on every append. This
is what lets chat booking span several messages ("tomorrow morning" ->
"10:30 works").

This module ships in the SAME commit as the docs/legal/*.md rewrite that
discloses this storage — see
docs/superpowers/plans/2026-08-02-whatsapp-mvp1-plan.md Task 3. Before this,
/privacy and /data-deletion stated no WhatsApp message content was ever
stored; that stopped being true the moment this module started writing rows.

RULE 9: logs carry turn counts and `phone[-4:]` only — NEVER message text.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.schema import WhatsAppSession

logger = structlog.get_logger()

# Keep in sync with the "last 10" / "30 days" figures in docs/legal/*.md —
# those documents quote these numbers, not a copy of them.
WA_SESSION_MAX_TURNS = 10
WA_SESSION_IDLE_DAYS = 30

_EMPTY_STATE: dict = {"turns": [], "draft": {}}


def _last4(phone: str | None) -> str:
    return (phone or "")[-4:] or "----"


async def _get_row(
    db: AsyncSession, branch_id: uuid.UUID, phone: str
) -> WhatsAppSession | None:
    """Most-recent matching row. No unique constraint exists on
    (branch_id, patient_phone) in the schema, so this is defensive against
    duplicates rather than assuming exactly one row."""
    result = await db.execute(
        select(WhatsAppSession)
        .where(
            WhatsAppSession.branch_id == branch_id,  # RULE 1
            WhatsAppSession.patient_phone == phone,
        )
        .order_by(WhatsAppSession.updated_at.desc())
        .limit(1)
    )
    return result.scalars().first()


async def load(db: AsyncSession, branch_id: uuid.UUID, phone: str) -> dict:
    """Current conversation state, or the empty shape if none exists yet."""
    row = await _get_row(db, branch_id, phone)
    if row is None or not row.session_data:
        return {"turns": [], "draft": {}}
    data = row.session_data
    return {
        "turns": list(data.get("turns") or []),
        "draft": dict(data.get("draft") or {}),
    }


async def append(
    db: AsyncSession, branch_id: uuid.UUID, phone: str, role: str, text: str
) -> None:
    """Append one turn, trimmed to the last `WA_SESSION_MAX_TURNS`.

    A brand-new dict is assigned to `session_data` (never mutated in
    place) so SQLAlchemy's change tracking picks up the JSONB write —
    mutating the existing dict object in place would be silently dropped
    on flush.
    """
    row = await _get_row(db, branch_id, phone)
    if row is None:
        row = WhatsAppSession(
            branch_id=branch_id, patient_phone=phone, session_data=dict(_EMPTY_STATE),
        )
        db.add(row)
        await db.flush()

    data = row.session_data or {}
    turns = list(data.get("turns") or [])
    turns.append({
        "role": role,
        "text": text,
        "at": datetime.now(timezone.utc).isoformat(),
    })
    turns = turns[-WA_SESSION_MAX_TURNS:]
    row.session_data = {"turns": turns, "draft": dict(data.get("draft") or {})}
    row.updated_at = datetime.now(timezone.utc)
    await db.commit()

    logger.info(
        "wa_session_turn_appended",
        branch_id=str(branch_id),
        phone_last4=_last4(phone),
        role=role,
        turn_count=len(turns),
    )


async def save_draft(
    db: AsyncSession, branch_id: uuid.UUID, phone: str, draft: dict
) -> None:
    """Persist hidden, branch-scoped tool state between patient messages."""
    row = await _get_row(db, branch_id, phone)
    if row is None:
        row = WhatsAppSession(
            branch_id=branch_id, patient_phone=phone, session_data=dict(_EMPTY_STATE),
        )
        db.add(row)
        await db.flush()
    data = dict(row.session_data or {})
    row.session_data = {
        **data,
        "turns": list(data.get("turns") or []),
        "draft": dict(draft or {}),
    }
    row.updated_at = datetime.now(timezone.utc)
    await db.commit()


def _webhook_text(message: dict) -> str:
    mtype = str(message.get("type") or "")
    payload = message.get(mtype) or {}
    if mtype == "text":
        return str(payload.get("body") or "")
    caption = str(payload.get("caption") or "")
    return caption or (f"[{mtype}]" if mtype else "[message]")


def _webhook_time(value) -> str:
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return datetime.now(timezone.utc).isoformat()


async def merge_history(
    db: AsyncSession,
    branch_id: uuid.UUID,
    business_phone: str,
    history_blocks: list[dict],
) -> int:
    """Digest Coexistence history while retaining only our disclosed window.

    Meta may send 180 days and thousands of messages in one webhook. Vachanam
    stores only the last ten turns per thread and discards messages older than
    30 days, matching the product's published data-minimization policy.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=WA_SESSION_IDLE_DAYS)
    changed = 0
    for block in history_blocks or []:
        for thread in block.get("threads") or []:
            phone = str(thread.get("id") or "")
            if not phone:
                continue
            incoming = []
            for message in thread.get("messages") or []:
                try:
                    sent_at = datetime.fromtimestamp(int(message.get("timestamp")), tz=timezone.utc)
                except (TypeError, ValueError, OSError):
                    continue
                if sent_at < cutoff:
                    continue
                incoming.append({
                    "id": str(message.get("id") or ""),
                    "role": "bot" if str(message.get("from") or "") == str(business_phone) else "patient",
                    "text": _webhook_text(message),
                    "at": sent_at.isoformat(),
                })
            if not incoming:
                continue

            row = await _get_row(db, branch_id, phone)
            if row is None:
                row = WhatsAppSession(
                    branch_id=branch_id, patient_phone=phone,
                    session_data=dict(_EMPTY_STATE),
                )
                db.add(row)
                await db.flush()
            data = dict(row.session_data or {})
            turns = list(data.get("turns") or [])
            known_ids = {str(turn.get("id")) for turn in turns if turn.get("id")}
            for turn in incoming:
                if turn["id"] and turn["id"] in known_ids:
                    continue
                turns.append(turn)
                if turn["id"]:
                    known_ids.add(turn["id"])
            turns.sort(key=lambda turn: str(turn.get("at") or ""))
            row.session_data = {
                **data,
                "turns": turns[-WA_SESSION_MAX_TURNS:],
                "draft": dict(data.get("draft") or {}),
            }
            row.updated_at = datetime.now(timezone.utc)
            changed += 1
    if changed:
        await db.flush()
    return changed


async def mirror_echoes(
    db: AsyncSession,
    branch_id: uuid.UUID,
    echoes: list[dict],
) -> int:
    """Mirror messages a receptionist sends from the WhatsApp Business app."""
    changed = 0
    for message in echoes or []:
        phone = str(message.get("to") or "")
        if not phone:
            continue
        row = await _get_row(db, branch_id, phone)
        if row is None:
            row = WhatsAppSession(
                branch_id=branch_id, patient_phone=phone,
                session_data=dict(_EMPTY_STATE),
            )
            db.add(row)
            await db.flush()
        data = dict(row.session_data or {})
        turns = list(data.get("turns") or [])
        message_id = str(message.get("id") or "")
        if message_id and any(str(turn.get("id") or "") == message_id for turn in turns):
            continue
        turns.append({
            "id": message_id,
            "role": "bot",
            "text": _webhook_text(message),
            "at": _webhook_time(message.get("timestamp")),
        })
        row.session_data = {
            **data,
            "turns": turns[-WA_SESSION_MAX_TURNS:],
            "draft": dict(data.get("draft") or {}),
        }
        row.updated_at = datetime.now(timezone.utc)
        changed += 1
    if changed:
        await db.flush()
    return changed


async def apply_edit_or_revoke(
    db: AsyncSession,
    branch_id: uuid.UUID,
    patient_phone: str,
    message: dict,
) -> bool:
    """Apply WhatsApp Business app edit/revoke events to stored chat state."""
    row = await _get_row(db, branch_id, patient_phone)
    if row is None:
        return False
    data = dict(row.session_data or {})
    turns = list(data.get("turns") or [])
    mtype = message.get("type")
    payload = message.get(mtype) or {}
    original_id = str(payload.get("original_message_id") or "")
    if not original_id:
        return False
    changed = False
    if mtype == "revoke":
        kept = [turn for turn in turns if str(turn.get("id") or "") != original_id]
        changed = len(kept) != len(turns)
        turns = kept
    else:
        replacement = payload.get("message") or {}
        for turn in turns:
            if str(turn.get("id") or "") == original_id:
                turn["text"] = _webhook_text(replacement)
                changed = True
    if not changed:
        return False
    row.session_data = {**data, "turns": turns, "draft": dict(data.get("draft") or {})}
    row.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return True


async def clear(db: AsyncSession, branch_id: uuid.UUID, phone: str) -> None:
    """Delete the conversation outright (manual reset / explicit clear).

    Patient erasure does NOT call this — it deletes the same rows itself
    (backend/services/patient_erasure.py), following the existing
    PatientMessage pattern so the erasure transaction stays a single
    caller-commits unit of work rather than being split by this
    function's own commit.
    """
    result = await db.execute(
        WhatsAppSession.__table__.delete().where(
            WhatsAppSession.branch_id == branch_id,
            WhatsAppSession.patient_phone == phone,
        )
    )
    await db.commit()
    logger.info(
        "wa_session_cleared",
        branch_id=str(branch_id),
        phone_last4=_last4(phone),
        rows_deleted=int(result.rowcount or 0),
    )

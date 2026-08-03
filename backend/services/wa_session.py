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
from datetime import datetime, timezone

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

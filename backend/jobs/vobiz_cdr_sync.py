"""Sync Vobiz call records into call_logs — authoritative call/minute metering.

Every run: pull recent Vobiz CDRs, map each call's dialed DID -> branch (RULE 5:
branch from the DID, never the caller), and upsert a CallLog row keyed by the
Vobiz call UUID (idempotent — re-syncing the same call updates, never duplicates).

This is independent of the agent process, so calls are logged even when the agent
drops/crashes or runs locally. The owner dashboard + admin console read call_logs,
so "calls answered" and voice minutes populate automatically.
"""
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select

import backend.database as _db_module
from backend.models.schema import Branch, CallLog
from backend.services.validators import normalize_did
from backend.services.vobiz_cdr import fetch_recent_calls

logger = structlog.get_logger()

# Re-pull a generous window each run so a call that was still in progress on the
# last sync is captured once Vobiz finalizes its duration. Idempotent upsert
# makes the overlap free.
LOOKBACK_MINUTES = 180


async def run_vobiz_cdr_sync() -> None:
    since = datetime.now(timezone.utc) - timedelta(minutes=LOOKBACK_MINUTES)
    records = await fetch_recent_calls(since)
    if not records:
        return

    async with _db_module.AsyncSessionLocal() as db:
        # DID -> branch map (normalized), built once per run.
        branches = (await db.execute(select(Branch))).scalars().all()
        did_to_branch = {}
        for b in branches:
            if b.did_number:
                did_to_branch[normalize_did(b.did_number)] = b.id

        upserted = 0
        for rec in records:
            # RULE 5: branch from the DIALED number. For inbound that is
            # to_number; for outbound the agent dialed from the DID (from_number).
            dialed = rec["to_number"] if rec["direction"] == "inbound" else rec["from_number"]
            if not dialed:
                continue
            branch_id = did_to_branch.get(normalize_did(dialed))
            if branch_id is None:
                continue  # call on a DID we don't own — skip (never cross-tenant)

            caller = rec["from_number"] if rec["direction"] == "inbound" else rec["to_number"]
            existing = (
                await db.execute(
                    select(CallLog).where(
                        CallLog.provider_call_id == rec["provider_call_id"]
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                # Update duration/answered — Vobiz may finalize after first sync.
                existing.duration_seconds = rec["duration_seconds"]
                existing.answered = rec["answered"]
            else:
                db.add(
                    CallLog(
                        branch_id=branch_id,
                        call_type=rec["direction"] or "inbound",
                        caller_last4=("".join(ch for ch in (caller or "") if ch.isdigit())[-4:] or None),
                        answered=rec["answered"],
                        started_at=rec["started_at"],
                        duration_seconds=rec["duration_seconds"],
                        booking_made=False,  # set by the agent path; CDR doesn't know
                        provider_call_id=rec["provider_call_id"],
                    )
                )
            upserted += 1
        await db.commit()
        logger.info("vobiz_cdr_synced", records=len(records), upserted=upserted)

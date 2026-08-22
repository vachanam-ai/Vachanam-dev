"""Cascade-rebook outbound calls — doctor went on leave, call every patient.

When a receptionist marks a doctor unavailable, cascade_for_unavailability
cancels the bookings and enqueues FollowupTask(task_type='cascade_rebook')
rows. Until now NOTHING dialed them — patients found out at the clinic door.

Every minute: pick due pending cascade_rebook tasks (attempts left), bump
attempt_count, push the next retry 30 minutes out, and dispatch an outbound
LiveKit agent call. The agent apologises for the doctor's leave and rebooks
the patient on the same call (same retention pattern as reminder calls).
The agent marks the task completed when a replacement booking is confirmed;
unanswered calls retry until max_attempts then go 'unreachable'.
"""
import json
import uuid
from datetime import datetime, timedelta, timezone

import structlog
from dotenv import load_dotenv
from sqlalchemy import and_, select

import backend.database as _db_module
from backend.models.schema import Branch, Doctor, FollowupTask, Patient, Token
from backend.services.telephony import (
    OutboundTrunkIsolationError,
    branch_outbound_trunk_id,
    validate_branch_outbound_trunk,
)

load_dotenv()

logger = structlog.get_logger()

AGENT_NAME = "vachanam-agent"
RETRY_BACKOFF_MIN = 30
BATCH_LIMIT = 10  # per run — keeps concurrent outbound calls bounded


async def _next_cascade_epoch(db) -> float | None:
    """When the earliest still-dialable cascade task is next due, or None when
    the queue is empty. Lets the 60s tick answer from Redis (#299)."""
    row = (
        await db.execute(
            select(FollowupTask.scheduled_at)
            .where(
                and_(
                    FollowupTask.task_type == "cascade_rebook",
                    FollowupTask.status.in_(["pending", "in_progress"]),
                    FollowupTask.attempt_count < FollowupTask.max_attempts,
                )
            )
            .order_by(FollowupTask.scheduled_at.asc())
            .limit(1)
        )
    ).first()
    return row[0].timestamp() if row else None


async def run_cascade_rebook_calls() -> None:
    from backend.config import settings as _settings
    from backend.jobs import wake_gate

    if not _settings.voice_plane_configured:
        # M15: warn (not silent) — a Render deploy missing LIVEKIT_* would
        # otherwise drop doctor-leave callbacks with no signal at all.
        logger.warning("cascade_rebook_skipped_no_voice_plane")
        return

    # #299: no cascade task due ⇒ answer from Redis, leave Postgres asleep.
    if not await wake_gate.should_run_scheduled("cascade"):
        return

    now = datetime.now(timezone.utc)
    async with _db_module.AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(FollowupTask, Patient, Doctor, Token, Branch)
                .join(Patient, FollowupTask.patient_id == Patient.id)
                .join(Doctor, FollowupTask.doctor_id == Doctor.id)
                .join(Token, FollowupTask.token_id == Token.id)
                .join(Branch, FollowupTask.branch_id == Branch.id)
                .where(
                    and_(
                        FollowupTask.task_type == "cascade_rebook",
                        FollowupTask.status.in_(["pending", "in_progress"]),
                        FollowupTask.attempt_count < FollowupTask.max_attempts,
                        FollowupTask.scheduled_at <= now,
                    )
                )
                .limit(BATCH_LIMIT)
            )
        ).all()

        for task, patient, doctor, token, branch in rows:
            if not patient.phone:
                task.status = "unreachable"  # nothing to dial
                await db.commit()
                continue
            try:
                outbound_trunk_id = branch_outbound_trunk_id(branch)
            except RuntimeError:
                logger.error(
                    "cascade_rebook_blocked_missing_branch_trunk",
                    branch_id=str(branch.id),
                    task_id=str(task.id),
                )
                continue
            result = await _dispatch_rebook_call(
                task, patient, doctor, token, branch, outbound_trunk_id
            )
            if result is None:
                # No patient attempt occurred (for example, another clinic is
                # already using this handset). Preserve its entire retry budget.
                continue
            task.attempt_count += 1
            task.scheduled_at = now + timedelta(minutes=RETRY_BACKOFF_MIN)
            if task.attempt_count >= task.max_attempts:
                # Last try fires now; mark unreachable so the dashboard stops
                # showing it as a perpetual "in progress" follow-up (L1).
                task.status = "unreachable"
            else:
                task.status = "in_progress"
            await db.commit()

        # #299: park until the next cascade task is actually due (retry backoff
        # included), so idle ticks never touch Postgres.
        await wake_gate.set_next_at("cascade", await _next_cascade_epoch(db))


async def _dispatch_rebook_call(
    task, patient, doctor, token, branch, outbound_trunk_id
) -> bool | None:
    try:
        outbound_trunk_id = validate_branch_outbound_trunk(
            branch, outbound_trunk_id
        )
    except OutboundTrunkIsolationError:
        logger.error(
            "cascade_rebook_blocked_unverified_branch_trunk",
            branch_id=str(branch.id),
            task_id=str(task.id),
        )
        return None

    # One outbound call per patient at a time across every dialing job — a
    # rebook landing in the same minute as a reminder rang the patient twice
    # (Vinay 2026-08-08). Skipping leaves the task queued for the next tick.
    from backend.services.outbound_guard import (
        claim_outbound_call,
        lock_key,
        release_outbound_call,
    )

    outbound_claim = await claim_outbound_call(
        getattr(patient, "phone", None), "rebook", branch.id
    )
    if not outbound_claim:
        return None
    try:
        from livekit import api as lk_api

        lkapi = lk_api.LiveKitAPI()
        try:
            room = f"rebook-{uuid.uuid4().hex[:10]}"
            await lkapi.agent_dispatch.create_dispatch(
                lk_api.CreateAgentDispatchRequest(
                    agent_name=AGENT_NAME,
                    room=room,
                    metadata=json.dumps(
                        {
                            "call_type": "cascade_rebook",
                            # RULE 5 is DID->branch for INBOUND; outbound has no
                            # dialed DID, so the branch must travel in metadata
                            # or a multi-clinic deploy resolves the wrong tenant.
                            "branch_id": str(task.branch_id),
                            "outbound_trunk_id": outbound_trunk_id,
                            "followup_task_id": str(task.id),
                            "outbound_lock_key": lock_key(patient.phone),
                            "outbound_lock_owner": outbound_claim,
                        }
                    ),
                )
            )
            # #423: verify a worker claimed it (loud log + empty-room cleanup on
            # loss). Flow needs no change — cascade already retries on backoff
            # via attempt_count regardless of this dispatch's fate.
            from backend.services.dispatch_verify import verify_or_cleanup

            if not await verify_or_cleanup(lkapi, room, f"cascade:{task.id}"):
                await release_outbound_call(
                    getattr(patient, "phone", None), outbound_claim, branch.id
                )
                return False
            logger.info(
                "cascade_rebook_call_dispatched",
                branch_id=str(task.branch_id),
                task_id=str(task.id),
                attempt=int(task.attempt_count or 0) + 1,
                patient_phone=patient.phone[-4:],
            )
            return True
        finally:
            try:
                await lkapi.aclose()
            except Exception as close_exc:  # noqa: BLE001 - handoff truth is authoritative
                logger.warning(
                    "cascade_rebook_livekit_close_failed",
                    error=str(close_exc)[:160],
                )
    except Exception as e:
        logger.error("cascade_rebook_dispatch_failed", task_id=str(task.id), error=str(e))
        await release_outbound_call(
            getattr(patient, "phone", None), outbound_claim, branch.id
        )
        return False

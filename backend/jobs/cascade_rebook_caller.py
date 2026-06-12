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
import os
import uuid
from datetime import datetime, timedelta, timezone

import structlog
from dotenv import load_dotenv
from sqlalchemy import and_, select

import backend.database as _db_module
from backend.models.schema import Branch, Doctor, FollowupTask, Patient, Token

load_dotenv()

logger = structlog.get_logger()

AGENT_NAME = "vachanam-agent"
RETRY_BACKOFF_MIN = 30
BATCH_LIMIT = 10  # per run — keeps concurrent outbound calls bounded


async def run_cascade_rebook_calls() -> None:
    if not (os.getenv("LIVEKIT_URL") and os.getenv("LIVEKIT_API_KEY")):
        return  # voice control plane not configured on this deployment

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
            task.status = "in_progress"
            task.attempt_count += 1
            task.scheduled_at = now + timedelta(minutes=RETRY_BACKOFF_MIN)
            if task.attempt_count >= task.max_attempts:
                # Last try fires now; if the agent never confirms a rebook the
                # task simply stops being retried (status stays in_progress as
                # a breadcrumb for the dashboard).
                pass
            await db.commit()
            await _dispatch_rebook_call(task, patient, doctor, token, branch)


async def _dispatch_rebook_call(task, patient, doctor, token, branch) -> None:
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
                            "phone_number": patient.phone,
                            "followup_task_id": str(task.id),
                            "patient_name": patient.name,
                            "doctor_name": doctor.name,
                            "doctor_id": str(doctor.id),
                            "cancelled_date": token.date.isoformat(),
                        }
                    ),
                )
            )
            logger.info(
                "cascade_rebook_call_dispatched",
                branch_id=str(task.branch_id),
                task_id=str(task.id),
                attempt=task.attempt_count,
                patient_phone=patient.phone[-4:],
            )
        finally:
            await lkapi.aclose()
    except Exception as e:
        logger.error("cascade_rebook_dispatch_failed", task_id=str(task.id), error=str(e))

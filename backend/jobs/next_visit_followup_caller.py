"""Dispatch outbound treatment follow-up calls (M2).

Every 15 min. Calling hours 09:00-20:00 branch-local IST (DPDP courtesy, RULE 8).
next_visit_book fires at/after 09:00 on its scheduled day; doctor_advice fires
ASAP. RULE 9: metadata carries ONLY operational fields + the doctor's message
(what_to_ask) — never steps_performed/next_steps. Reuses the reminder dispatch."""
from __future__ import annotations
import json
import uuid
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo
import structlog
from sqlalchemy import select
from backend.database import AsyncSessionLocal
from backend.models.schema import FollowupTask, Branch, Doctor, Patient, TreatmentNote
from backend.services.telephony import branch_outbound_trunk_id

logger = structlog.get_logger()
IST = ZoneInfo("Asia/Kolkata")
CALL_START_H, CALL_END_H = 9, 20
AGENT_NAME = "vachanam-agent"


def _is_due(task, now_ist: datetime) -> bool:
    if not (CALL_START_H <= now_ist.hour < CALL_END_H):
        return False
    sched = task.scheduled_date or now_ist.date()
    if sched > now_ist.date():
        return False
    return task.task_type in ("next_visit_book", "doctor_advice")


async def _dispatch(task, branch, doctor, patient, target_date) -> bool:
    """Create the outbound agent dispatch. Returns True ONLY when create_dispatch
    succeeded; False on any exception (logged, never raised). The caller marks the
    task done on True and retries/keeps pending on False — dispatch-then-mutate so a
    failure can never strand a task as a dead row (FIXLOG #160, mirrors #151)."""
    try:
        from livekit import api as lk_api
        lkapi = lk_api.LiveKitAPI()
        try:
            meta = {"call_type": task.task_type, "branch_id": str(branch.id),
                    "outbound_trunk_id": branch_outbound_trunk_id(branch),
                    "phone_number": patient.phone, "task_id": str(task.id),
                    "patient_name": patient.name, "doctor_name": doctor.name,
                    "doctor_id": str(doctor.id), "message": task.what_to_ask or ""}
            # RULE 9: target_date/window are a BOOKING concern only — never leak a
            # booking hint onto a doctor_advice task linked to the same note.
            if target_date and task.task_type == "next_visit_book":
                meta["target_date"] = target_date
                meta["window"] = 2
            await lkapi.agent_dispatch.create_dispatch(lk_api.CreateAgentDispatchRequest(
                agent_name=AGENT_NAME, room=f"followup-{uuid.uuid4().hex[:10]}",
                metadata=json.dumps(meta)))
            logger.info("followup_call_dispatched", task_id=str(task.id),
                        call_type=task.task_type, phone_last4=(patient.phone or "")[-4:])
            return True
        finally:
            await lkapi.aclose()
    except Exception as e:  # noqa: BLE001
        logger.error("followup_dispatch_failed", task_id=str(task.id), error=str(e)[:160])
        return False


async def _next_due_epoch(db, now_ist: datetime) -> float | None:
    """When the earliest pending voice follow-up becomes dialable, or None when
    none are pending. A task is due once scheduled_date has arrived and we are
    inside calling hours — so a future task's due moment is CALL_START_H on its
    scheduled day (#299)."""
    row = (
        await db.execute(
            select(FollowupTask.scheduled_date)
            .where(
                FollowupTask.status == "pending",
                FollowupTask.channel == "voice",
                FollowupTask.task_type.in_(["next_visit_book", "doctor_advice"]),
            )
            .order_by(FollowupTask.scheduled_date.asc())
            .limit(1)
        )
    ).first()
    if not row:
        return None
    sched = row[0] or now_ist.date()
    if sched <= now_ist.date():
        return now_ist.timestamp()  # due now (or overdue) — keep ticking
    return datetime.combine(sched, dtime(CALL_START_H), tzinfo=IST).timestamp()


async def run_next_visit_followups(now: datetime | None = None) -> int:
    from backend.jobs import wake_gate

    now_ist = (now or datetime.now(IST)).astimezone(IST)
    if not (CALL_START_H <= now_ist.hour < CALL_END_H):
        return 0
    # #299: the next task isn't dialable yet ⇒ answer from Redis and leave
    # Postgres asleep. Schedule-driven (not producer-driven), so a task created
    # by ANY path is still picked up: the job recomputes the due time from the
    # database on every real pass, and wake_gate fails open on Redis trouble.
    if not await wake_gate.should_run_scheduled("followups"):
        return 0
    dispatched = 0
    async with AsyncSessionLocal() as db:
        tasks = (await db.execute(select(FollowupTask).where(
            FollowupTask.status == "pending", FollowupTask.channel == "voice",
            FollowupTask.task_type.in_(["next_visit_book", "doctor_advice"])))).scalars().all()
        for t in tasks:
            if not _is_due(t, now_ist):
                continue
            branch = (await db.execute(select(Branch).where(Branch.id == t.branch_id))).scalar_one_or_none()
            doctor = (await db.execute(select(Doctor).where(Doctor.id == t.doctor_id))).scalar_one_or_none()
            patient = (await db.execute(select(Patient).where(Patient.id == t.patient_id))).scalar_one_or_none()
            if not (branch and doctor and patient and patient.phone):
                t.status = "unreachable"
                logger.warning("followup_skipped_missing_data", task_id=str(t.id))
                await db.commit()   # COMMIT PER TASK — one task can't roll back the batch
                continue
            target_date = None
            if t.treatment_note_id:
                tn = (await db.execute(select(TreatmentNote).where(
                    TreatmentNote.id == t.treatment_note_id))).scalar_one_or_none()
                if tn and tn.is_final:
                    t.status = "completed"   # treatment closed since enqueue
                    await db.commit()
                    continue
                if tn and tn.next_reporting_date:
                    target_date = tn.next_reporting_date.isoformat()
            # DISPATCH-THEN-MUTATE (FIXLOG #160, mirrors #151): do NOT flip in_progress
            # before dialing — the run query only pulls 'pending' and NO job requeues a
            # stranded 'in_progress' FollowupTask, so a flip-before-dispatch crash strands
            # the task forever (permanent miss). Dispatch first; mutate on the result.
            t.attempt_count = (t.attempt_count or 0) + 1
            ok = await _dispatch(t, branch, doctor, patient, target_date)
            if ok:
                # Call dispatched. The agent enriches response_summary on call-end
                # (later task); the task is now non-pending so the next 15-min tick
                # will NOT re-dial it (no duplicate calls).
                t.status = "completed"
                dispatched += 1
            else:
                # Dispatch failed: exhaust → unreachable, else keep pending so the next
                # tick retries (self-healing). Never marked done before a real dispatch.
                t.status = "unreachable" if t.attempt_count >= (t.max_attempts or 3) else "pending"
            await db.commit()   # COMMIT PER TASK

        # #299: park until the next follow-up is actually dialable. Capped by
        # wake_gate.SAFETY_SECONDS, so nothing sleeps longer than an hour.
        await wake_gate.set_next_at("followups", await _next_due_epoch(db, now_ist))
    return dispatched

"""Dispatch outbound treatment follow-up calls (M2).

Every 15 min. Calling hours 09:00-20:00 branch-local IST (DPDP courtesy, RULE 8).
next_visit_book fires at/after 09:00 on its scheduled day; doctor_advice fires
ASAP. RULE 9: metadata carries ONLY operational fields + the doctor's message
(what_to_ask) — never steps_performed/next_steps. Reuses the reminder dispatch."""
from __future__ import annotations
import json
import uuid
from datetime import datetime
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


async def _dispatch(task, branch, doctor, patient, target_date) -> None:
    from livekit import api as lk_api
    lkapi = lk_api.LiveKitAPI()
    try:
        meta = {"call_type": task.task_type, "branch_id": str(branch.id),
                "outbound_trunk_id": branch_outbound_trunk_id(branch),
                "phone_number": patient.phone, "task_id": str(task.id),
                "patient_name": patient.name, "doctor_name": doctor.name,
                "doctor_id": str(doctor.id), "message": task.what_to_ask or ""}
        if target_date:
            meta["target_date"] = target_date
            meta["window"] = 2
        await lkapi.agent_dispatch.create_dispatch(lk_api.CreateAgentDispatchRequest(
            agent_name=AGENT_NAME, room=f"followup-{uuid.uuid4().hex[:10]}",
            metadata=json.dumps(meta)))
        logger.info("followup_call_dispatched", task_id=str(task.id),
                    call_type=task.task_type, phone_last4=(patient.phone or "")[-4:])
    finally:
        await lkapi.aclose()


async def run_next_visit_followups(now: datetime | None = None) -> int:
    now_ist = (now or datetime.now(IST)).astimezone(IST)
    if not (CALL_START_H <= now_ist.hour < CALL_END_H):
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
                continue
            target_date = None
            if t.treatment_note_id:
                tn = (await db.execute(select(TreatmentNote).where(
                    TreatmentNote.id == t.treatment_note_id))).scalar_one_or_none()
                if tn and tn.is_final:
                    t.status = "completed"   # treatment closed since enqueue
                    continue
                if tn and tn.next_reporting_date:
                    target_date = tn.next_reporting_date.isoformat()
            t.attempt_count = (t.attempt_count or 0) + 1
            t.status = "in_progress"
            try:
                await _dispatch(t, branch, doctor, patient, target_date)
                dispatched += 1
            except Exception as e:  # noqa: BLE001
                logger.error("followup_dispatch_failed", task_id=str(t.id), error=str(e)[:160])
                t.status = "unreachable" if t.attempt_count >= (t.max_attempts or 3) else "pending"
        await db.commit()
    return dispatched

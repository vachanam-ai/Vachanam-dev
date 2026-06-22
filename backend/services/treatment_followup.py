"""Enqueue/cancel the next-visit follow-up call for a treatment note (M2).

Idempotent: at most one PENDING next_visit_book task per (patient, doctor). A
newer note supersedes the prior pending task; a final note cancels and enqueues
nothing. RULE 9: only operational fields ride the task — never steps_performed /
next_steps."""
from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.schema import TreatmentNote, FollowupTask


async def _cancel_pending(patient_id: uuid.UUID, doctor_id: uuid.UUID, db: AsyncSession) -> None:
    # Superseded pending tasks are DELETED, not completed: a pending task was
    # never dialed, so deleting it leaves no phantom "completed" follow-up row
    # (no ghost in the upcoming thread, no over-count in reporting). Only
    # status=='pending' is touched — an in_progress (dispatched) task is never
    # affected, so no live call is dropped. FK-safe: nothing references
    # followup_tasks.id.
    await db.execute(
        delete(FollowupTask)
        .where(FollowupTask.patient_id == patient_id, FollowupTask.doctor_id == doctor_id,
               FollowupTask.task_type == "next_visit_book", FollowupTask.status == "pending")
    )


async def sync_note_followup(note: TreatmentNote, followup_question: str | None,
                             created_by: uuid.UUID | None, db: AsyncSession) -> None:
    await _cancel_pending(note.patient_id, note.doctor_id, db)
    if note.is_final:
        await db.commit()
        return
    if not note.next_reporting_date and not followup_question:
        await db.commit()
        return
    db.add(FollowupTask(
        branch_id=note.branch_id, doctor_id=note.doctor_id, patient_id=note.patient_id,
        treatment_note_id=note.id, task_type="next_visit_book", channel="voice",
        what_to_ask=followup_question, scheduled_date=note.visit_date + timedelta(days=1),
        status="pending", created_by_user_id=created_by,
    ))
    await db.commit()

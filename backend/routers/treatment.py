"""Treatment progress notes (M1) + follow-up thread (M2).

RULE 1: every route is branch-scoped (assert_branch_access) and super_admin is
denied (forbid_admin). steps_performed/next_steps are operational notes —
dashboard-only, never spoken or sent to calendar/SMS (RULE 9).
"""
import uuid
from datetime import date

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.middleware.auth_middleware import CurrentUser, get_current_user, forbid_admin
from backend.middleware.branch_guard import assert_branch_access
from backend.models.schema import TreatmentNote, Patient, FollowupTask
from backend.services.treatment_logic import resolve_is_final

logger = structlog.get_logger()
router = APIRouter(dependencies=[Depends(forbid_admin)])


class NoteIn(BaseModel):
    branch_id: uuid.UUID
    doctor_id: uuid.UUID
    visit_date: date
    token_id: uuid.UUID | None = None
    steps_performed: str | None = Field(None, max_length=4000)
    next_steps: str | None = Field(None, max_length=2000)
    next_reporting_date: date | None = None
    is_final: bool | None = None
    followup_question: str | None = Field(None, max_length=2000)

    @field_validator("visit_date")
    @classmethod
    def _not_future(cls, v: date) -> date:
        if v > date.today():
            raise ValueError("visit_date cannot be in the future")
        return v


class ReplyIn(BaseModel):
    branch_id: uuid.UUID
    doctor_id: uuid.UUID
    message: str = Field(..., min_length=1, max_length=2000)
    next_reporting_date: date | None = None
    treatment_note_id: uuid.UUID | None = None


class NoteOut(BaseModel):
    id: uuid.UUID
    visit_date: date
    steps_performed: str | None
    next_steps: str | None
    next_reporting_date: date | None
    is_final: bool
    doctor_id: uuid.UUID


async def _load_patient(patient_id: uuid.UUID, branch_id: uuid.UUID, db: AsyncSession) -> Patient:
    pat = (await db.execute(
        select(Patient).where(Patient.id == patient_id, Patient.branch_id == branch_id)
    )).scalar_one_or_none()
    if pat is None:
        raise HTTPException(status_code=404, detail="patient not found in branch")
    return pat


@router.post("/patients/{patient_id}/treatment-notes", status_code=201, response_model=NoteOut)
async def create_note(
    patient_id: uuid.UUID,
    body: NoteIn,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NoteOut:
    await assert_branch_access(user, str(body.branch_id), db)
    await _load_patient(patient_id, body.branch_id, db)
    if body.next_reporting_date and body.next_reporting_date < body.visit_date:
        raise HTTPException(status_code=422, detail="next_reporting_date before visit_date")
    is_final = resolve_is_final(body.is_final, body.next_steps)
    note = TreatmentNote(
        branch_id=body.branch_id, doctor_id=body.doctor_id, patient_id=patient_id,
        token_id=body.token_id, visit_date=body.visit_date,
        steps_performed=body.steps_performed, next_steps=body.next_steps,
        next_reporting_date=body.next_reporting_date,
        is_final=is_final,
        created_by_user_id=uuid.UUID(user.user_id) if user.user_id else None,
    )
    db.add(note)
    await db.commit()
    await db.refresh(note)
    # M2 (Task 6): next_reporting_date / followup_question → pending next_visit_book;
    # is_final cancels any pending follow-up. Idempotent (one pending per patient+doctor).
    from backend.services.treatment_followup import sync_note_followup
    await sync_note_followup(note, body.followup_question,
                             uuid.UUID(user.user_id) if user.user_id else None, db)
    logger.info(
        "treatment_note_created",
        branch_id=str(body.branch_id),
        patient_phone_last4=None,
        note_id=str(note.id),
        is_final=is_final,
        action="treatment.note.create",
    )
    return note


@router.patch("/treatment-notes/{note_id}", response_model=NoteOut)
async def edit_note(
    note_id: uuid.UUID,
    body: NoteIn,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NoteOut:
    await assert_branch_access(user, str(body.branch_id), db)
    if body.next_reporting_date and body.next_reporting_date < body.visit_date:
        raise HTTPException(status_code=422, detail="next_reporting_date before visit_date")
    note = (await db.execute(
        select(TreatmentNote).where(
            TreatmentNote.id == note_id,
            TreatmentNote.branch_id == body.branch_id,
        )
    )).scalar_one_or_none()
    if note is None:
        raise HTTPException(status_code=404, detail="note not found")
    note.visit_date = body.visit_date
    note.steps_performed = body.steps_performed
    note.next_steps = body.next_steps
    note.next_reporting_date = body.next_reporting_date
    note.is_final = resolve_is_final(body.is_final, body.next_steps)
    await db.commit()
    await db.refresh(note)
    # M2 (Task 6): re-schedule or cancel the follow-up to match the edited note.
    from backend.services.treatment_followup import sync_note_followup
    await sync_note_followup(note, body.followup_question,
                             uuid.UUID(user.user_id) if user.user_id else None, db)
    logger.info(
        "treatment_note_updated",
        branch_id=str(body.branch_id),
        note_id=str(note.id),
        is_final=note.is_final,
        action="treatment.note.edit",
    )
    return note


@router.get("/patients/{patient_id}/treatment-notes")
async def list_notes(
    patient_id: uuid.UUID,
    branch_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await assert_branch_access(user, str(branch_id), db)
    rows = (await db.execute(
        select(TreatmentNote).where(
            TreatmentNote.patient_id == patient_id,
            TreatmentNote.branch_id == branch_id,
        ).order_by(TreatmentNote.visit_date.asc(), TreatmentNote.created_at.asc())
    )).scalars().all()
    status = "completed" if (rows and rows[-1].is_final) else ("active" if rows else "none")
    return {
        "treatment_status": status,
        "notes": [
            NoteOut.model_validate(r, from_attributes=True).model_dump(mode="json")
            for r in rows
        ],
    }


@router.get("/branches/{branch_id}/treatment-patients")
async def list_patients(
    branch_id: uuid.UUID,
    doctor_id: uuid.UUID | None = None,
    status: str = "all",
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await assert_branch_access(user, str(branch_id), db)
    # Latest note per patient (branch-scoped) drives active/last-visit/next-date.
    q = select(TreatmentNote).where(TreatmentNote.branch_id == branch_id)
    if doctor_id:
        q = q.where(TreatmentNote.doctor_id == doctor_id)
    notes = (await db.execute(
        q.order_by(
            TreatmentNote.patient_id,
            TreatmentNote.visit_date.asc(),
            TreatmentNote.created_at.asc(),
        )
    )).scalars().all()
    latest: dict[uuid.UUID, TreatmentNote] = {}
    for n in notes:
        latest[n.patient_id] = n  # last wins = newest
    pat_ids = list(latest.keys())
    if not pat_ids:
        return {"patients": []}
    pats = {
        p.id: p
        for p in (await db.execute(
            select(Patient).where(
                Patient.id.in_(pat_ids),
                Patient.branch_id == branch_id,  # final tripwire (RULE 1)
            )
        )).scalars().all()
    }
    out = []
    for pid, n in latest.items():
        active = not n.is_final
        if status == "active" and not active:
            continue
        p = pats.get(pid)
        if p is None:
            continue
        out.append({
            "patient_id": str(pid),
            "name": p.name,
            "phone_last4": (p.phone or "")[-4:],
            "doctor_id": str(n.doctor_id),
            "last_visit_date": n.visit_date.isoformat(),
            "next_reporting_date": n.next_reporting_date.isoformat() if n.next_reporting_date else None,
            "active": active,
        })
    return {"patients": out}


# --- M2 (Task 7): follow-up thread (read + doctor reply) ---
# Thread = next_visit_book + doctor_advice rows for one patient+branch, oldest first.
# A doctor reply (any language) is relayed verbatim via what_to_ask; it NEVER writes
# steps_performed/next_steps (RULE 9 — those are dashboard-only operational notes).


@router.get("/patients/{patient_id}/followups")
async def list_followups(
    patient_id: uuid.UUID,
    branch_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await assert_branch_access(user, str(branch_id), db)
    rows = (await db.execute(
        select(FollowupTask).where(
            FollowupTask.patient_id == patient_id,
            FollowupTask.branch_id == branch_id,
            FollowupTask.task_type.in_(["next_visit_book", "doctor_advice"]),
        ).order_by(FollowupTask.created_at.asc())
    )).scalars().all()
    return {
        "thread": [
            {
                "id": str(t.id),
                "task_type": t.task_type,
                "message": t.what_to_ask,
                "response": t.response_summary,
                "status": t.status,
                "scheduled_date": t.scheduled_date.isoformat() if t.scheduled_date else None,
                "created_at": t.created_at.isoformat(),
            }
            for t in rows
        ]
    }


@router.post("/patients/{patient_id}/followups", status_code=201)
async def doctor_reply(
    patient_id: uuid.UUID,
    body: ReplyIn,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await assert_branch_access(user, str(body.branch_id), db)
    await _load_patient(patient_id, body.branch_id, db)
    task = FollowupTask(
        branch_id=body.branch_id,
        doctor_id=body.doctor_id,
        patient_id=patient_id,
        treatment_note_id=body.treatment_note_id,
        task_type="doctor_advice",
        channel="voice",
        what_to_ask=body.message,
        scheduled_date=date.today(),
        status="pending",
        created_by_user_id=uuid.UUID(user.user_id) if user.user_id else None,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    logger.info(
        "followup_doctor_reply_created",
        branch_id=str(body.branch_id),
        task_id=str(task.id),
        action="treatment.followup.reply",
    )
    return {"id": str(task.id), "task_type": task.task_type, "status": task.status}

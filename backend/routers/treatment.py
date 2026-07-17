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
from backend.middleware.rate_limit import default_limit  # SEC #4
from backend.models.schema import TreatmentNote, Patient, FollowupTask, Doctor
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
        # B7: this Pydantic check runs against server-UTC today, but clinics
        # live in branch-local time (IST is UTC+5:30). Between 00:00-05:30 IST
        # server-UTC "today" is still the previous calendar day, so a legit
        # same-day note was rejected as "future". Allow +1 day of slack here
        # (covers every branch tz up to UTC+14) and enforce the real
        # branch-local "not future" bound in the route where the branch tz is
        # known (see create_note / edit_note).
        from datetime import timedelta

        if v > date.today() + timedelta(days=1):
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


async def _load_doctor(doctor_id: uuid.UUID, branch_id: uuid.UUID, db: AsyncSession) -> Doctor:
    doc = (await db.execute(
        select(Doctor).where(Doctor.id == doctor_id, Doctor.branch_id == branch_id)
    )).scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="doctor not found in branch")
    return doc


async def _assert_visit_not_future(
    visit_date: date, branch_id: uuid.UUID, db: AsyncSession
) -> None:
    """B7: reject a visit_date after the BRANCH-local today. The Pydantic
    validator allows +1 day slack (server-UTC vs branch tz); the real bound is
    enforced here, where the branch timezone is available."""
    from backend.routers.queue import _branch_today

    branch_today = await _branch_today(branch_id, db)
    if visit_date > branch_today:
        raise HTTPException(status_code=422, detail="visit_date cannot be in the future")


async def _forced_doctor_id(
    user: CurrentUser, branch_id: uuid.UUID, db: AsyncSession
) -> uuid.UUID | None:
    """A doctor login acts ONLY as its own Doctor row (Vinay 2026-07-16: a
    doctor could read/write every doctor's treatments — the client-side
    doctor_id filter was optional and forgeable). Returns the linked Doctor id
    to FORCE for role=doctor; None for other roles (no forcing). An unlinked
    doctor login (should not happen — add_staff binds it) gets 403."""
    if user.role != "doctor":
        return None
    own = (
        await db.execute(
            select(Doctor.id).where(
                Doctor.branch_id == branch_id,
                Doctor.user_id == uuid.UUID(user.user_id),
            )
        )
    ).scalar_one_or_none()
    if own is None:
        raise HTTPException(status_code=403, detail="No doctor profile linked to this login")
    return own


@router.post("/patients/{patient_id}/treatment-notes", status_code=201, response_model=NoteOut)
async def create_note(
    patient_id: uuid.UUID,
    body: NoteIn,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NoteOut:
    await assert_branch_access(user, str(body.branch_id), db)
    own = await _forced_doctor_id(user, body.branch_id, db)
    if own is not None and body.doctor_id != own:
        raise HTTPException(status_code=403, detail="Doctors can only write their own treatment notes")
    await _load_patient(patient_id, body.branch_id, db)
    await _load_doctor(body.doctor_id, body.branch_id, db)
    await _assert_visit_not_future(body.visit_date, body.branch_id, db)  # B7
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
    own = await _forced_doctor_id(user, body.branch_id, db)
    if own is not None and body.doctor_id != own:
        raise HTTPException(status_code=403, detail="Doctors can only edit their own treatment notes")
    await _load_doctor(body.doctor_id, body.branch_id, db)
    await _assert_visit_not_future(body.visit_date, body.branch_id, db)  # B7
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
    if own is not None and note.doctor_id != own:
        raise HTTPException(status_code=403, detail="Doctors can only edit their own treatment notes")
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


@router.get("/patients/{patient_id}/treatment-notes", dependencies=[Depends(default_limit)])
async def list_notes(
    patient_id: uuid.UUID,
    branch_id: uuid.UUID,
    doctor_id: uuid.UUID | None = None,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await assert_branch_access(user, str(branch_id), db)
    # doctor_id: scope the visit history to ONE treatment thread — a patient
    # can run concurrent treatments with different doctors. A doctor login is
    # FORCED to its own thread regardless of what the client sent.
    own = await _forced_doctor_id(user, branch_id, db)
    if own is not None:
        doctor_id = own
    q = select(TreatmentNote).where(
        TreatmentNote.patient_id == patient_id,
        TreatmentNote.branch_id == branch_id,
    )
    if doctor_id:
        q = q.where(TreatmentNote.doctor_id == doctor_id)
    rows = (await db.execute(
        q.order_by(TreatmentNote.visit_date.asc(), TreatmentNote.created_at.asc())
    )).scalars().all()
    status = "completed" if (rows and rows[-1].is_final) else ("active" if rows else "none")
    return {
        "treatment_status": status,
        "notes": [
            NoteOut.model_validate(r, from_attributes=True).model_dump(mode="json")
            for r in rows
        ],
    }


@router.get("/branches/{branch_id}/treatment-patients", dependencies=[Depends(default_limit)])
async def list_patients(
    branch_id: uuid.UUID,
    doctor_id: uuid.UUID | None = None,
    status: str = "all",
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await assert_branch_access(user, str(branch_id), db)
    # A doctor login sees ONLY its own patients — forced server-side.
    own = await _forced_doctor_id(user, branch_id, db)
    if own is not None:
        doctor_id = own
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
    # One treatment THREAD per (patient, doctor) — a patient can run two
    # treatments at once (e.g. dental with Srinivas + skin with Lakshmi) and
    # collapsing to one row per patient hid one of them (prod 2026-07-03).
    latest: dict[tuple[uuid.UUID, uuid.UUID], TreatmentNote] = {}
    for n in notes:
        latest[(n.patient_id, n.doctor_id)] = n  # last wins = newest
    pat_ids = list({pid for (pid, _did) in latest.keys()})
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
    # Doctor names so the list shows WHO each patient reports to and the UI
    # can filter by doctor — no per-row lookup.
    doc_names = {
        d.id: d.name
        for d in (await db.execute(
            select(Doctor).where(
                Doctor.id.in_({n.doctor_id for n in latest.values()}),
                Doctor.branch_id == branch_id,
            )
        )).scalars().all()
    }
    out = []
    for (pid, _did), n in latest.items():
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
            "doctor_name": doc_names.get(n.doctor_id),
            "last_visit_date": n.visit_date.isoformat(),
            "next_reporting_date": n.next_reporting_date.isoformat() if n.next_reporting_date else None,
            "active": active,
        })
    return {"patients": out}


class EndTreatmentIn(BaseModel):
    branch_id: uuid.UUID
    # When set, only this doctor's treatment thread ends (a patient can run two
    # treatments at once). Omitted = end every thread for the patient.
    # NOTE: end-treatment NEVER erases patient data — erasure lives ONLY on the
    # Patients page (DELETE /patients/{id}, Vinay 2026-07-12).
    doctor_id: uuid.UUID | None = None


@router.post("/patients/{patient_id}/end-treatment")
async def end_treatment(
    patient_id: uuid.UUID,
    body: EndTreatmentIn,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """End a treatment (one-time visitor cleanup / treatment finished).

    Deletes the treatment notes for the thread (the patient drops off the
    Treatments list) and completes any pending follow-up tasks so no more
    calls go out. Patient PII is untouched — erasure is the Patients page's
    job. RULE 1: branch-scoped; RULE 9: audit row keeps IDs only.
    """
    await assert_branch_access(user, str(body.branch_id), db)
    # A doctor login may only end ITS OWN treatment thread — never another
    # doctor's, never "all threads" for the patient.
    own = await _forced_doctor_id(user, body.branch_id, db)
    if own is not None:
        body.doctor_id = own
    await _load_patient(patient_id, body.branch_id, db)

    note_filter = [
        TreatmentNote.patient_id == patient_id,
        TreatmentNote.branch_id == body.branch_id,
    ]
    task_filter = [
        FollowupTask.patient_id == patient_id,
        FollowupTask.branch_id == body.branch_id,
    ]
    if body.doctor_id:
        note_filter.append(TreatmentNote.doctor_id == body.doctor_id)
        task_filter.append(FollowupTask.doctor_id == body.doctor_id)
    # FK ORDER: FollowupTask.treatment_note_id -> treatment_notes is
    # RESTRICT — clear links before deleting the notes.
    await db.execute(
        FollowupTask.__table__.update().where(*task_filter)
        .values(treatment_note_id=None)
    )
    res = await db.execute(TreatmentNote.__table__.delete().where(*note_filter))
    notes_deleted = int(res.rowcount or 0)

    # No more follow-up calls for this thread.
    await db.execute(
        FollowupTask.__table__.update()
        .where(*task_filter, FollowupTask.status.in_(("pending", "in_progress")))
        .values(status="completed")
    )
    await db.commit()

    from backend.services.audit_service import write_audit_row

    await write_audit_row(
        action="treatment.ended",
        resource_type="patient",
        resource_id=str(patient_id),
        user_id=uuid.UUID(user.user_id) if user.user_id else None,
        branch_id=body.branch_id,
        metadata={"doctor_id": str(body.doctor_id) if body.doctor_id else None},
    )
    logger.info(
        "treatment_ended",
        patient_id=str(patient_id),
        branch_id=str(body.branch_id),
        notes_deleted=notes_deleted,
        action="treatment.ended",
    )
    return {"ended": True}


# --- M2 (Task 7): follow-up thread (read + doctor reply) ---
# Thread = next_visit_book + doctor_advice rows for one patient+branch, oldest first.
# A doctor reply (any language) is relayed verbatim via what_to_ask; it NEVER writes
# steps_performed/next_steps (RULE 9 — those are dashboard-only operational notes).


@router.get("/patients/{patient_id}/followups", dependencies=[Depends(default_limit)])
async def list_followups(
    patient_id: uuid.UUID,
    branch_id: uuid.UUID,
    doctor_id: uuid.UUID | None = None,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await assert_branch_access(user, str(branch_id), db)
    own = await _forced_doctor_id(user, branch_id, db)
    if own is not None:
        doctor_id = own
    q = select(FollowupTask).where(
        FollowupTask.patient_id == patient_id,
        FollowupTask.branch_id == branch_id,
        FollowupTask.task_type.in_(["next_visit_book", "doctor_advice"]),
    )
    if doctor_id:  # one thread per (patient, doctor) treatment
        q = q.where(FollowupTask.doctor_id == doctor_id)
    rows = (await db.execute(q.order_by(FollowupTask.created_at.asc()))).scalars().all()
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
    own = await _forced_doctor_id(user, body.branch_id, db)
    if own is not None and body.doctor_id != own:
        raise HTTPException(status_code=403, detail="Doctors can only reply on their own treatment threads")
    await _load_patient(patient_id, body.branch_id, db)
    await _load_doctor(body.doctor_id, body.branch_id, db)
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

    # #299: doctor_advice dials ASAP — drop the follow-up job's parked due time
    # so it runs on the very next tick instead of waiting it out.
    from backend.jobs import wake_gate

    await wake_gate.clear_next_at("followups")

    logger.info(
        "followup_doctor_reply_created",
        branch_id=str(body.branch_id),
        task_id=str(task.id),
        action="treatment.followup.reply",
    )
    return {"id": str(task.id), "task_type": task.task_type, "status": task.status}

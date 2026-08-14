"""Patient Information view (clinic-only). GET a branch's patients with their
last-seen doctor; PATCH name/age/phone with a duplicate guard.

RULE 1: every route branch-scoped (assert_branch_access); super_admin denied
(forbid_admin). RULE 9: name/age/phone are PII — never logged.
"""
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.middleware.auth_middleware import CurrentUser, get_current_user, forbid_admin
from backend.middleware.branch_guard import assert_branch_access
from backend.middleware.rate_limit import default_limit  # SEC #4: throttle PII reads
from backend.models.schema import Patient, Token, Doctor
from backend.services.validators import normalize_indian_phone

logger = structlog.get_logger()
router = APIRouter(dependencies=[Depends(forbid_admin)])


class PatientRow(BaseModel):
    id: uuid.UUID
    name: str
    age: int | None
    phone: str | None
    is_primary: bool
    last_doctor: str | None


class PatientEdit(BaseModel):
    branch_id: uuid.UUID
    name: str | None = Field(None, min_length=1, max_length=255)
    age: int | None = Field(None, ge=0, le=120)
    phone: str | None = None


@router.get("/branches/{branch_id}/patients", dependencies=[Depends(default_limit)])
async def list_patients(
    branch_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await assert_branch_access(user, str(branch_id), db)

    # Latest token per patient (date desc, created_at desc) -> doctor name.
    # One pass: rank tokens per patient, keep rank 1, join the doctor. No N+1.
    ranked = (
        select(
            Token.patient_id.label("pid"),
            Doctor.name.label("doctor_name"),
            func.row_number().over(
                partition_by=Token.patient_id,
                order_by=(Token.date.desc(), Token.created_at.desc()),
            ).label("rn"),
        )
        .join(Doctor, Token.doctor_id == Doctor.id)
        .where(Token.branch_id == branch_id)
        .subquery()
    )
    last_doc = select(ranked.c.pid, ranked.c.doctor_name).where(ranked.c.rn == 1).subquery()

    rows = (
        await db.execute(
            select(Patient, last_doc.c.doctor_name)
            .outerjoin(last_doc, last_doc.c.pid == Patient.id)
            # Erased patients (retention job or clinic delete) never show —
            # an "[erased]" row is noise, not information (Vinay 2026-07-12).
            .where(Patient.branch_id == branch_id,
                   Patient.anonymized_at.is_(None))
            .order_by(func.lower(Patient.name))
        )
    ).all()

    patients = [
        PatientRow(
            id=p.id, name=p.name, age=p.age, phone=p.phone,
            is_primary=p.is_primary, last_doctor=doc_name,
        )
        for (p, doc_name) in rows
    ]
    return {"patients": patients}


@router.get(
    "/branches/{branch_id}/upcoming",
    dependencies=[Depends(default_limit)],
)
async def upcoming_appointments(
    branch_id: uuid.UUID,
    days: int = 15,
    doctor_id: str | None = None,
    on_date: str | None = None,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Confirmed bookings from today through today+days (default 15), for the
    Patients page forward view (Vinay 2026-07-15). Filters: doctor_id, on_date
    (YYYY-MM-DD). RULE 1 branch-scoped; one join, no N+1."""
    from datetime import date as _date
    from datetime import timedelta as _td

    from backend.routers.queue import _branch_today

    await assert_branch_access(user, str(branch_id), db)
    days = max(1, min(days, 90))
    today = await _branch_today(branch_id, db)
    end = today + _td(days=days)

    # A doctor login sees ONLY their own patients (Vinay 2026-07-15): force the
    # filter to their linked Doctor row, ignoring any doctor_id they pass. An
    # unlinked doctor account (shouldn't happen — add_staff binds it) sees none.
    if user.role == "doctor":
        own = (
            await db.execute(
                select(Doctor.id).where(
                    Doctor.branch_id == branch_id,
                    Doctor.user_id == uuid.UUID(user.user_id),
                )
            )
        ).scalar_one_or_none()
        if own is None:
            return {"appointments": [], "days": days}
        doctor_id = str(own)

    q = (
        select(Token, Patient.name, Doctor.name.label("doc"))
        .join(Patient, Patient.id == Token.patient_id)
        .join(Doctor, Doctor.id == Token.doctor_id)
        .where(
            Token.branch_id == branch_id,  # RULE 1
            Token.status == "confirmed",
            Token.date >= today,
            Token.date <= end,
        )
    )
    if doctor_id:
        try:
            q = q.where(Token.doctor_id == uuid.UUID(doctor_id))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid doctor_id")
    if on_date:
        try:
            q = q.where(Token.date == _date.fromisoformat(on_date))
        except ValueError:
            raise HTTPException(status_code=400, detail="on_date must be YYYY-MM-DD")

    rows = (
        await db.execute(
            q.order_by(Token.date, Token.appointment_time.is_(None), Token.appointment_time)
        )
    ).all()
    return {
        "appointments": [
            {
                "patient_name": pname,
                "doctor_name": doc,
                "date": t.date.isoformat(),
                "time": t.appointment_time.strftime("%H:%M") if t.appointment_time else None,
                "token_number": t.token_number,
            }
            for (t, pname, doc) in rows
        ],
        "days": days,
    }


@router.delete("/{patient_id}")
async def delete_patient(
    patient_id: uuid.UUID,
    branch_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Erase a patient's personal data (DPDP right to erasure) — the ONLY
    place a clinic can erase a patient (Vinay 2026-07-12; end-treatment no
    longer erases). Same shared path as the automatic retention job. The row
    survives anonymized for aggregate counts but never appears in any list."""
    await assert_branch_access(user, str(branch_id), db)
    patient = (
        await db.execute(
            select(Patient).where(
                Patient.id == patient_id, Patient.branch_id == branch_id
            )
        )
    ).scalar_one_or_none()
    if patient is None:
        raise HTTPException(status_code=404, detail="patient not found in branch")

    from backend.services.patient_erasure import erase_patient_pii

    await erase_patient_pii(db, patient)
    await db.commit()

    from backend.services.audit_service import write_audit_row

    await write_audit_row(
        action="patient.erased",
        resource_type="patient",
        resource_id=str(patient_id),
        user_id=uuid.UUID(user.user_id) if user.user_id else None,
        branch_id=branch_id,
    )
    return {"erased": True}


@router.patch("/{patient_id}")
async def edit_patient(
    patient_id: uuid.UUID,
    body: PatientEdit,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PatientRow:
    await assert_branch_access(user, str(body.branch_id), db)
    patient = (
        await db.execute(
            select(Patient).where(
                Patient.id == patient_id, Patient.branch_id == body.branch_id
            )
        )
    ).scalar_one_or_none()
    if patient is None:
        raise HTTPException(status_code=404, detail="patient not found in branch")

    # B13: min_length=1 passes a whitespace-only " ", which strips to "" and was
    # saved as the patient's name (also dodges the dup guard and lower("")
    # comparisons). Reject an all-whitespace name post-strip.
    if body.name is not None and not body.name.strip():
        raise HTTPException(status_code=422, detail="name cannot be empty")
    new_name = body.name.strip() if body.name is not None else patient.name
    new_phone = patient.phone
    if body.phone is not None:
        try:
            new_phone = normalize_indian_phone(body.phone)
        except ValueError:
            raise HTTPException(status_code=422, detail="phone must be a 10-digit Indian mobile")

    # Duplicate guard: another patient in this branch with the same (phone, lower(name)).
    if (new_name.lower() != patient.name.lower()) or (new_phone != patient.phone):
        if new_phone is not None:
            clash = (
                await db.execute(
                    select(Patient.id).where(
                        and_(
                            Patient.branch_id == body.branch_id,
                            Patient.phone == new_phone,
                            func.lower(Patient.name) == new_name.lower(),
                            Patient.id != patient.id,
                        )
                    )
                )
            ).first()
            if clash is not None:
                raise HTTPException(status_code=409, detail="duplicate_patient")

    phone_changed = new_phone != patient.phone
    patient.name = new_name
    patient.phone = new_phone
    if body.age is not None:
        patient.age = body.age

    # Re-evaluate ownership if the phone moved: if the new phone has no other
    # primary, this patient becomes its owner.
    if phone_changed and new_phone is not None:
        has_primary = (
            await db.execute(
                select(Patient.id).where(
                    and_(
                        Patient.branch_id == body.branch_id,
                        Patient.phone == new_phone,
                        Patient.is_primary.is_(True),
                        Patient.id != patient.id,
                    )
                )
            )
        ).first()
        patient.is_primary = has_primary is None

    await db.commit()
    logger.info("patient_edited", branch_id=str(body.branch_id), patient_id=str(patient.id),
                phone_changed=phone_changed)
    return PatientRow(
        id=patient.id, name=patient.name, age=patient.age, phone=patient.phone,
        is_primary=patient.is_primary, last_doctor=None,
    )

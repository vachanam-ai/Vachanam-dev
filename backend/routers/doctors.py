"""Doctors CRUD router.

Endpoints:
  GET  /doctors/{branch_id}                      — list active doctors (receptionist + org_admin)
  POST /doctors/{branch_id}                      — create doctor (org_admin only)
  PATCH /doctors/{branch_id}/{doctor_id}         — edit doctor (org_admin only)
  DELETE /doctors/{branch_id}/{doctor_id}        — soft delete (org_admin only)
  PATCH /doctors/{branch_id}/{doctor_id}/stop-walkins-today — set walkins_closed_today_date (receptionist + org_admin)

Auto-defaults on POST (spec §5.2):
  - booking_type='appointment': pre_appointment_reminder=True, post_treatment_followup=True
  - booking_type='token':       both False
  (caller may override by setting either field explicitly in body)

After POST/PATCH: if doctor is token-type AND a calendar_id is available,
  calls GoogleCalendarService.upsert_doctor_hours_event — best-effort, wrapped
  in try/except; result stored on doctor.calendar_event_id_recurring.

RBAC:
  - GET + stop-walkins-today: receptionist + org_admin (assert_branch_access alone)
  - POST / PATCH / DELETE: org_admin only (require_role("org_admin"))

Audit: @audit decorator on POST, PATCH, DELETE.

Per CLAUDE.md Rule 1: every query filters by branch_id.
"""
import uuid
from datetime import time
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.middleware.auth_middleware import CurrentUser, get_current_user
from backend.middleware.branch_guard import assert_branch_access
from backend.models.schema import Branch, Doctor
from backend.services.audit_service import audit
from backend.services.calendar_service import GoogleCalendarService

logger = structlog.get_logger()
router = APIRouter()


# ---------------------------------------------------------------------------
# Role guard helper
# ---------------------------------------------------------------------------

async def _require_org_admin(
    current_user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    """Reject any role other than org_admin with 403.

    super_admin is already blocked upstream by assert_branch_access.
    receptionist and doctor roles are rejected here for write operations.
    """
    if current_user.role != "org_admin":
        logger.warning(
            "doctor_write_access_denied",
            user_id=current_user.user_id,
            role=current_user.role,
        )
        raise HTTPException(
            status_code=403,
            detail="org_admin role required for this operation",
        )
    return current_user


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class DoctorIn(BaseModel):
    """Request body for POST (create) and PATCH (update) doctor."""

    name: str = Field(..., min_length=1, max_length=255)
    specialization: Optional[str] = Field(default=None, max_length=100)
    booking_type: str = Field(..., pattern="^(token|appointment)$")
    working_hours_start: Optional[str] = Field(
        default=None,
        description="HH:MM format e.g. '09:00'",
    )
    working_hours_end: Optional[str] = Field(
        default=None,
        description="HH:MM format e.g. '17:00'",
    )
    available_weekdays: Optional[list[int]] = Field(
        default=None,
        description="ISO int list 0=Mon, 6=Sun e.g. [0,1,2,3,4]",
    )
    slot_duration_minutes: Optional[int] = Field(default=None, ge=5, le=240)
    max_concurrent_per_slot: Optional[int] = Field(default=None, ge=1, le=50)
    daily_token_limit: Optional[int] = Field(default=None, ge=1, le=500)
    pre_appointment_reminder: Optional[bool] = None
    post_treatment_followup: Optional[bool] = None
    whatsapp_number: Optional[str] = Field(default=None, max_length=20)
    invited_email: Optional[str] = Field(default=None, max_length=255)
    google_calendar_id: Optional[str] = Field(default=None, max_length=255)
    is_default_doctor: Optional[bool] = None


class DoctorOut(BaseModel):
    """Response shape for a doctor record."""

    id: str
    branch_id: str
    user_id: Optional[str]  # L4: lets the doctor-role UI match its own card
    name: str
    specialization: Optional[str]
    booking_type: str
    working_hours_start: Optional[str]
    working_hours_end: Optional[str]
    available_weekdays: list
    slot_duration_minutes: Optional[int]
    max_concurrent_per_slot: Optional[int]
    daily_token_limit: Optional[int]
    pre_appointment_reminder: bool
    post_treatment_followup: bool
    walkins_closed_today_date: Optional[str]
    calendar_event_id_recurring: Optional[str]
    google_calendar_id: Optional[str]
    whatsapp_number: Optional[str]
    invited_email: Optional[str]
    is_default_doctor: bool
    status: str


class StopWalkinsResponse(BaseModel):
    walkins_closed_today_date: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_time(value: Optional[str], field_name: str) -> Optional[time]:
    """Parse "HH:MM" string to datetime.time. Returns None if value is None."""
    if value is None:
        return None
    try:
        h, m = value.split(":")
        return time(int(h), int(m))
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid {field_name} format — expected 'HH:MM' e.g. '09:00'",
        )


def _doctor_to_out(doc: Doctor) -> DoctorOut:
    """Serialize a Doctor ORM row to the response model.

    Captures all needed values while the session is still open
    (avoids DetachedInstanceError — CLAUDE.md pattern).
    """
    return DoctorOut(
        id=str(doc.id),
        branch_id=str(doc.branch_id),
        user_id=str(doc.user_id) if doc.user_id else None,
        name=doc.name,
        specialization=doc.specialization,
        booking_type=doc.booking_type,
        working_hours_start=(
            doc.working_hours_start.strftime("%H:%M")
            if doc.working_hours_start else None
        ),
        working_hours_end=(
            doc.working_hours_end.strftime("%H:%M")
            if doc.working_hours_end else None
        ),
        available_weekdays=doc.available_weekdays or [0, 1, 2, 3, 4, 5, 6],
        slot_duration_minutes=doc.slot_duration_minutes,
        max_concurrent_per_slot=doc.max_concurrent_per_slot,
        daily_token_limit=doc.daily_token_limit,
        pre_appointment_reminder=doc.pre_appointment_reminder,
        post_treatment_followup=doc.post_treatment_followup,
        walkins_closed_today_date=(
            doc.walkins_closed_today_date.isoformat()
            if doc.walkins_closed_today_date else None
        ),
        calendar_event_id_recurring=doc.calendar_event_id_recurring,
        google_calendar_id=doc.google_calendar_id,
        whatsapp_number=doc.whatsapp_number,
        invited_email=doc.invited_email,
        is_default_doctor=doc.is_default_doctor,
        status=doc.status,
    )


async def _maybe_upsert_recurring_cal_event(
    doc: Doctor,
    branch: Branch,
    db: AsyncSession,
    old_calendar_id: str | None = None,
) -> None:
    """Best-effort: create/update recurring clinic-hours Calendar event.

    Called after POST/PATCH for EVERY doctor type when a calendar_id is
    available (doctor or branch level) — clinics expect each doctor's hours
    visible in the calendar regardless of token/appointment booking. Any
    exception is caught and logged — never raises (spec §5.2 constraint 4).

    TD-023: when the effective calendar CHANGES, the stored recurring event id
    belongs to the OLD calendar — PATCHing it against the new calendar 404s and
    the old calendar keeps a stale hours block. So on a calendar change we delete
    the old event from the old calendar and create a fresh one on the new.
    """
    cal_id = doc.google_calendar_id or branch.google_calendar_id
    if not cal_id:
        return
    if not doc.working_hours_start or not doc.working_hours_end:
        logger.warning(
            "skip_recurring_cal_event_no_hours",
            doctor_id=str(doc.id),
            branch_id=str(branch.id),
        )
        return

    # Calendar moved? Drop the stale event from the OLD calendar and create new.
    existing_event_id = doc.calendar_event_id_recurring
    if old_calendar_id and old_calendar_id != cal_id and existing_event_id:
        try:
            await GoogleCalendarService().delete_event(old_calendar_id, existing_event_id)
            logger.info(
                "recurring_cal_event_moved_deleted_old",
                doctor_id=str(doc.id), old_calendar=old_calendar_id[-12:],
            )
        except Exception as _del_exc:
            logger.warning("recurring_cal_old_delete_failed", error=str(_del_exc))
        existing_event_id = None  # force a fresh create on the new calendar

    try:
        svc = GoogleCalendarService()
        event_id = await svc.upsert_doctor_hours_event(
            calendar_id=cal_id,
            doctor_name=doc.name,
            working_hours_start=doc.working_hours_start,
            working_hours_end=doc.working_hours_end,
            available_weekdays=doc.available_weekdays or [0, 1, 2, 3, 4, 5, 6],
            existing_event_id=existing_event_id,
        )
        doc.calendar_event_id_recurring = event_id
        await db.commit()
        logger.info(
            "recurring_cal_event_upserted",
            doctor_id=str(doc.id),
            branch_id=str(branch.id),
            event_id=event_id,
        )
    except Exception as exc:
        # Best-effort — log and continue. Booking is unaffected.
        logger.warning(
            "recurring_cal_event_failed",
            doctor_id=str(doc.id),
            branch_id=str(branch.id),
            error=str(exc),
        )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get(
    "/{branch_id}",
    response_model=list[DoctorOut],
)
async def list_doctors(
    branch_id: str,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[DoctorOut]:
    """List active doctors for a branch.

    Accessible by receptionist + org_admin (assert_branch_access blocks super_admin).
    Returns only status='active' doctors, always scoped to branch_id (Rule 1).
    """
    await assert_branch_access(current_user, branch_id, db)

    try:
        branch_uuid = uuid.UUID(branch_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid branch_id format")

    result = await db.execute(
        select(Doctor).where(
            Doctor.branch_id == branch_uuid,  # MANDATORY — Rule 1 tripwire
            Doctor.status == "active",
        ).order_by(Doctor.name)
    )
    doctors = result.scalars().all()

    # Capture values inside session block to avoid DetachedInstanceError
    out = [_doctor_to_out(d) for d in doctors]

    logger.info(
        "doctors_listed",
        branch_id=branch_id,
        count=len(out),
        user_id=current_user.user_id,
    )
    return out


@router.post(
    "/{branch_id}",
    response_model=DoctorOut,
    status_code=201,
)
@audit("doctor.create", resource_type="doctor")
async def create_doctor(
    branch_id: str,
    body: DoctorIn,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    _admin: CurrentUser = Depends(_require_org_admin),
    db: AsyncSession = Depends(get_db),
) -> DoctorOut:
    """Create a new doctor under a branch.

    org_admin only. Auto-sets reminder defaults based on booking_type:
      appointment → pre_appointment_reminder=True, post_treatment_followup=True
      token       → both False
    Caller may override by setting either field explicitly in the body.
    """
    await assert_branch_access(current_user, branch_id, db)

    try:
        branch_uuid = uuid.UUID(branch_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid branch_id format")

    # Fetch branch for cal fallback and audit
    branch_result = await db.execute(
        select(Branch).where(Branch.id == branch_uuid)
    )
    branch = branch_result.scalar_one_or_none()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")

    # Plan doctor cap (repricing 2026-07-11): Starter 1 / Clinic 5 / Multi
    # unlimited. Counted per ORG (all branches), active doctors only.
    from backend.models.schema import Organization
    from backend.services.billing_math import PLANS

    org = (
        await db.execute(
            select(Organization).where(Organization.id == branch.org_id)
        )
    ).scalar_one_or_none()
    plan_def = PLANS.get(org.plan if org else "clinic")
    if plan_def and plan_def.max_doctors is not None:
        active_count = (
            await db.execute(
                select(func.count())
                .select_from(Doctor)
                .join(Branch, Doctor.branch_id == Branch.id)
                .where(Branch.org_id == branch.org_id, Doctor.status == "active")
            )
        ).scalar_one()
        if active_count >= plan_def.max_doctors:
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Your {plan_def.display_name} plan includes up to "
                    f"{plan_def.max_doctors} doctor(s). Upgrade to add more."
                ),
            )

    # Auto-defaults: appointment → reminders on; token → reminders off
    is_appointment = body.booking_type == "appointment"
    pre_reminder = (
        body.pre_appointment_reminder
        if body.pre_appointment_reminder is not None
        else is_appointment
    )
    post_followup = (
        body.post_treatment_followup
        if body.post_treatment_followup is not None
        else is_appointment
    )

    doc = Doctor(
        branch_id=branch_uuid,
        name=body.name,
        specialization=body.specialization,
        booking_type=body.booking_type,
        working_hours_start=_parse_time(body.working_hours_start, "working_hours_start"),
        working_hours_end=_parse_time(body.working_hours_end, "working_hours_end"),
        available_weekdays=body.available_weekdays if body.available_weekdays is not None else [0, 1, 2, 3, 4, 5, 6],
        slot_duration_minutes=body.slot_duration_minutes,
        max_concurrent_per_slot=body.max_concurrent_per_slot,
        daily_token_limit=body.daily_token_limit,
        pre_appointment_reminder=pre_reminder,
        post_treatment_followup=post_followup,
        whatsapp_number=body.whatsapp_number,
        invited_email=body.invited_email,
        google_calendar_id=body.google_calendar_id,
        is_default_doctor=body.is_default_doctor or False,
        status="active",
    )
    db.add(doc)
    await db.flush()
    # G8: at most ONE default doctor per branch — the agent's out-of-scope
    # fallback picks `next(d for d in doctors if d.is_default_doctor)`, which is
    # non-deterministic with two defaults. Setting a new default clears the rest.
    if doc.is_default_doctor:
        await db.execute(
            sa_update(Doctor)
            .where(Doctor.branch_id == branch_uuid, Doctor.id != doc.id)
            .values(is_default_doctor=False)
        )
    await db.commit()

    logger.info(
        "doctor_created",
        branch_id=branch_id,
        doctor_id=str(doc.id),
        booking_type=doc.booking_type,
        user_id=current_user.user_id,
    )

    # Set audit context for @audit decorator
    request.state.audit_resource_id = str(doc.id)
    request.state.audit_user_id = current_user.user_id
    request.state.audit_branch_id = branch_id

    # Best-effort: upsert recurring Cal event for token-doctor
    await _maybe_upsert_recurring_cal_event(doc, branch, db)

    return _doctor_to_out(doc)


@router.patch(
    "/{branch_id}/{doctor_id}",
    response_model=DoctorOut,
)
@audit("doctor.update", resource_type="doctor")
async def update_doctor(
    branch_id: str,
    doctor_id: str,
    body: DoctorIn,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    _admin: CurrentUser = Depends(_require_org_admin),
    db: AsyncSession = Depends(get_db),
) -> DoctorOut:
    """Edit a doctor record.

    org_admin only. Applies only fields present in the request body
    (model_dump(exclude_unset=True) pattern). After update, if doctor is
    token-type and has a calendar_id, upserts the recurring hours event.
    """
    await assert_branch_access(current_user, branch_id, db)

    try:
        branch_uuid = uuid.UUID(branch_id)
        doctor_uuid = uuid.UUID(doctor_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format")

    # Fetch branch for cal fallback
    branch_result = await db.execute(
        select(Branch).where(Branch.id == branch_uuid)
    )
    branch = branch_result.scalar_one_or_none()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")

    result = await db.execute(
        select(Doctor).where(
            Doctor.id == doctor_uuid,
            Doctor.branch_id == branch_uuid,  # MANDATORY — Rule 1 tripwire
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Doctor not found")

    changed = body.model_dump(exclude_unset=True)
    hours_weekdays_changed = (
        "working_hours_start" in changed
        or "working_hours_end" in changed
        or "available_weekdays" in changed
        or "booking_type" in changed
        or "google_calendar_id" in changed
    )
    # TD-023: remember the OLD effective calendar so the recurring-event upsert
    # can move the hours block off it when the calendar id changes.
    old_effective_cal = doc.google_calendar_id or branch.google_calendar_id

    # Apply scalar fields; parse time strings
    for field, value in changed.items():
        if field == "working_hours_start":
            doc.working_hours_start = _parse_time(value, "working_hours_start")
        elif field == "working_hours_end":
            doc.working_hours_end = _parse_time(value, "working_hours_end")
        else:
            setattr(doc, field, value)

    # G8: promoting this doctor to default demotes every other in the branch.
    if changed.get("is_default_doctor") is True:
        await db.execute(
            sa_update(Doctor)
            .where(Doctor.branch_id == branch_uuid, Doctor.id != doc.id)
            .values(is_default_doctor=False)
        )

    await db.commit()

    logger.info(
        "doctor_updated",
        branch_id=branch_id,
        doctor_id=doctor_id,
        fields_changed=list(changed.keys()),
        user_id=current_user.user_id,
    )

    request.state.audit_resource_id = doctor_id
    request.state.audit_user_id = current_user.user_id
    request.state.audit_branch_id = branch_id

    # Best-effort: re-sync recurring Cal event if relevant fields changed.
    # Pass the old calendar so a calendar change moves the hours block (TD-023).
    if hours_weekdays_changed:
        await _maybe_upsert_recurring_cal_event(
            doc, branch, db, old_calendar_id=old_effective_cal
        )

    return _doctor_to_out(doc)


@router.delete(
    "/{branch_id}/{doctor_id}",
    status_code=204,
)
@audit("doctor.delete", resource_type="doctor")
async def soft_delete_doctor(
    branch_id: str,
    doctor_id: str,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    _admin: CurrentUser = Depends(_require_org_admin),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Soft delete a doctor by setting status='inactive'.

    org_admin only. Does NOT delete any tokens or follow-up tasks — the
    doctor record is retained for audit trail (DPDP Act 2023).
    """
    await assert_branch_access(current_user, branch_id, db)

    try:
        branch_uuid = uuid.UUID(branch_id)
        doctor_uuid = uuid.UUID(doctor_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format")

    result = await db.execute(
        select(Doctor).where(
            Doctor.id == doctor_uuid,
            Doctor.branch_id == branch_uuid,  # MANDATORY — Rule 1 tripwire
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Doctor not found")

    doc.status = "inactive"
    await db.commit()

    logger.info(
        "doctor_soft_deleted",
        branch_id=branch_id,
        doctor_id=doctor_id,
        user_id=current_user.user_id,
    )

    request.state.audit_resource_id = doctor_id
    request.state.audit_user_id = current_user.user_id
    request.state.audit_branch_id = branch_id


@router.patch(
    "/{branch_id}/{doctor_id}/stop-walkins-today",
    response_model=StopWalkinsResponse,
)
@audit("doctor.walkins_closed_today", resource_type="doctor")
async def stop_walkins_today(
    branch_id: str,
    doctor_id: str,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StopWalkinsResponse:
    """Set walkins_closed_today_date to CURRENT_DATE for a doctor.

    Accessible by receptionist + org_admin. The walk-in preflight check
    (Task 10) compares walkins_closed_today_date to date.today() to decide
    whether to block new walk-ins. Date auto-expires next day by comparison.
    """
    await assert_branch_access(current_user, branch_id, db)

    try:
        branch_uuid = uuid.UUID(branch_id)
        doctor_uuid = uuid.UUID(doctor_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format")

    result = await db.execute(
        select(Doctor).where(
            Doctor.id == doctor_uuid,
            Doctor.branch_id == branch_uuid,  # MANDATORY — Rule 1 tripwire
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Doctor not found")

    from backend.routers.queue import _branch_today

    today = await _branch_today(branch_uuid, db)  # branch tz, not server UTC
    doc.walkins_closed_today_date = today
    await db.commit()

    logger.info(
        "walkins_closed_today",
        branch_id=branch_id,
        doctor_id=doctor_id,
        date=today.isoformat(),
        user_id=current_user.user_id,
    )

    request.state.audit_resource_id = doctor_id
    request.state.audit_user_id = current_user.user_id
    request.state.audit_branch_id = branch_id

    return StopWalkinsResponse(walkins_closed_today_date=today.isoformat())

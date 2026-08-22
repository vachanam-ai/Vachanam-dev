"""Doctor availability router.

Mounted at /availability in backend/main.py.

Endpoints:
  POST   /availability/{branch_id}/{doctor_id}
           Body: {date_from, date_to, reason}
           Action: marks doctor unavailable, cascade-cancels existing tokens,
                   schedules cascade_rebook followup tasks.
           Role: staff (receptionist + org_admin).
           Rate: 10 req/min per user (availability_post_limit).

  GET    /availability/{branch_id}/{doctor_id}?from=YYYY-MM-DD&to=YYYY-MM-DD
           Lists DoctorUnavailability rows in date range (inclusive).
           Role: receptionist + org_admin.

  DELETE /availability/{branch_id}/{doctor_id}/{date}
           Removes a single unavailability date row (undo a fat-fingered leave).
           Role: staff — whoever can mark leave can undo the marking. (Already
           cancelled tokens are not auto-restored; undo only stops further
           confusion and reopens the slot for new bookings.)

  GET    /availability/{branch_id}/{doctor_id}/affected?from=YYYY-MM-DD&to=YYYY-MM-DD
           Preflight: returns count + list of confirmed tokens that WOULD be cancelled.
           Used by frontend drawer to show impact before confirm.
           PII: returns patient_first_name + phone[-4:] (branch-scoped users have access).
           Role: receptionist + org_admin.

Audit events:
  availability.mark_unavailable  — on POST (metadata: date_from, date_to, doctor_id; NO patient PII)
  availability.cascade_cancel    — 1 row per cancelled token (metadata: token_id, doctor_id, date)
  availability.remove            — on DELETE (metadata: date, doctor_id)

Per CLAUDE.md:
  Rule 1: every query filters by branch_id — mandatory
  Rule 9: structlog JSON on every significant event
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Optional

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.middleware.auth_middleware import CurrentUser, get_current_user
from backend.middleware.branch_guard import assert_branch_access
from backend.middleware.rate_limit import _make_endpoint_limiter
from backend.models.schema import (
    Doctor, DoctorDateSchedule, DoctorUnavailability, Patient, Token,
)
from backend.services.audit_service import audit, write_audit_row
from backend.services.cascade_cancel import cascade_for_unavailability
from backend.services.clinic_cache import invalidate as invalidate_clinic_cache
from backend.services.doctor_schedule import (
    effective_recurring_schedule,
    validate_sessions,
)

logger = structlog.get_logger()
router = APIRouter()

# Rate limiter: 10 POST requests per minute per user/IP — spec constraint 7
availability_post_limit = _make_endpoint_limiter(times=10, seconds=60)


# ---------------------------------------------------------------------------
# Role guard helper (same pattern as doctors.py _require_org_admin)
# ---------------------------------------------------------------------------

async def _require_org_admin(
    current_user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    """Reject any role other than org_admin with 403.

    super_admin is blocked upstream by assert_branch_access.
    receptionist and doctor are rejected here for write operations.
    """
    if current_user.role != "org_admin":
        logger.warning(
            "availability_write_access_denied",
            user_id=current_user.user_id,
            role=current_user.role,
        )
        raise HTTPException(
            status_code=403,
            detail="org_admin role required for this operation",
        )
    return current_user


async def _require_staff(
    current_user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    """Allow receptionist + org_admin (front-desk operations). Reception marks
    doctor leave at the desk; super_admin/doctor are rejected for writes."""
    if current_user.role not in ("org_admin", "receptionist"):
        logger.warning(
            "availability_write_access_denied",
            user_id=current_user.user_id,
            role=current_user.role,
        )
        raise HTTPException(
            status_code=403,
            detail="receptionist or org_admin role required",
        )
    return current_user


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class MarkUnavailableRequest(BaseModel):
    date_from: date
    date_to: date
    reason: Optional[str] = Field(default=None, max_length=500)


class MarkUnavailableResponse(BaseModel):
    unavailable_dates: int
    cancelled_tokens: int
    followups_scheduled: int


class UnavailabilityRow(BaseModel):
    id: str
    branch_id: str
    doctor_id: str
    date: str
    reason: Optional[str]
    created_by_user_id: Optional[str]
    created_at: str


class AffectedToken(BaseModel):
    token_id: str
    token_number: Optional[int]
    date: str
    appointment_time: Optional[str]
    patient_first_name: str
    patient_phone_last4: Optional[str]


class AffectedTokensResponse(BaseModel):
    count: int
    tokens: list[AffectedToken]


class DateScheduleIn(BaseModel):
    sessions: list[dict[str, str]] = Field(default_factory=list)
    token_limit: Optional[int] = Field(default=None, ge=1, le=500)
    notes: Optional[str] = Field(default=None, max_length=500)


class DateScheduleRangeIn(DateScheduleIn):
    date_from: date
    date_to: date


class DateScheduleOut(BaseModel):
    date: str
    status: str
    source: str
    sessions: list[dict[str, str]]
    token_limit: Optional[int]
    notes: Optional[str]
    is_published: bool


class DateScheduleRangeOut(BaseModel):
    schedules: list[DateScheduleOut]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_date(value: str, field_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid {field_name} format — expected YYYY-MM-DD",
        )


def _unavail_to_out(row: DoctorUnavailability) -> UnavailabilityRow:
    """Serialize a DoctorUnavailability ORM row inside the open session."""
    return UnavailabilityRow(
        id=str(row.id),
        branch_id=str(row.branch_id),
        doctor_id=str(row.doctor_id),
        date=row.date.isoformat(),
        reason=row.reason,
        created_by_user_id=(
            str(row.created_by_user_id) if row.created_by_user_id else None
        ),
        created_at=row.created_at.isoformat(),
    )


def _schedule_writer_allowed(current_user: CurrentUser, doctor: Doctor) -> None:
    """Staff may publish any branch doctor; a doctor may publish only self."""
    if current_user.role in ("org_admin", "receptionist"):
        return
    if current_user.role == "doctor" and str(doctor.user_id) == current_user.user_id:
        return
    raise HTTPException(status_code=403, detail="You may only publish your own doctor schedule")


def _date_slots(sessions: list[dict[str, str]], duration: int | None) -> set:
    if not duration:
        return set()
    result = set()
    step = timedelta(minutes=duration)
    for session in sessions:
        current = datetime.combine(date.min, datetime.strptime(session["start"], "%H:%M").time())
        end = datetime.combine(date.min, datetime.strptime(session["end"], "%H:%M").time())
        while current + step <= end:
            result.add(current.time())
            current += step
    return result


async def _sync_date_schedule_range_events(
    branch_id: uuid.UUID,
    doctor_id: uuid.UUID,
    target_dates: list[date],
) -> None:
    """Best-effort calendar projection after the authoritative response."""
    from backend.database import AsyncSessionLocal
    from backend.services.doctor_calendar import sync_date_schedule_events

    for target_date in target_dates:
        async with AsyncSessionLocal() as db:
            try:
                await sync_date_schedule_events(db, branch_id, doctor_id, target_date)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "date_schedule_calendar_sync_failed",
                    branch_id=str(branch_id),
                    doctor_id=str(doctor_id),
                    date=target_date.isoformat(),
                    error=str(exc)[:200],
                )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.put(
    "/{branch_id}/{doctor_id}/schedule-range",
    response_model=DateScheduleRangeOut,
)
@audit("availability.schedule_range_publish", resource_type="doctor_date_schedule")
async def publish_date_schedule_range(
    branch_id: str,
    doctor_id: str,
    body: DateScheduleRangeIn,
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DateScheduleRangeOut:
    """Atomically publish identical sessions for an inclusive 1-31 date range."""
    await assert_branch_access(current_user, branch_id, db)
    try:
        branch_uuid = uuid.UUID(branch_id)
        doctor_uuid = uuid.UUID(doctor_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format")

    span = (body.date_to - body.date_from).days
    if span < 0 or span > 30:
        raise HTTPException(status_code=422, detail="Schedule range must contain 1 to 31 dates")
    target_dates = [body.date_from + timedelta(days=offset) for offset in range(span + 1)]

    # Shared counterpart to doctor.update's exclusive config lock. Acquire it
    # before loading booking_type/slot duration so range validation cannot use
    # a stale doctor shape while those fields are being committed.
    await db.execute(
        text("SELECT pg_advisory_xact_lock_shared(hashtextextended(:k, 0))"),
        {"k": f"schedule-config:{branch_uuid}:{doctor_uuid}"},
    )

    doctor = (
        await db.execute(
            select(Doctor).where(
                Doctor.id == doctor_uuid,
                Doctor.branch_id == branch_uuid,
                Doctor.status == "active",
            )
        )
    ).scalar_one_or_none()
    if doctor is None:
        raise HTTPException(status_code=404, detail="Doctor not found")
    _schedule_writer_allowed(current_user, doctor)

    from backend.routers.queue import _branch_today

    branch_today = await _branch_today(branch_uuid, db)
    if body.date_from < branch_today:
        raise HTTPException(status_code=422, detail="Cannot change a past schedule")
    if body.date_to > branch_today + timedelta(days=365):
        raise HTTPException(status_code=422, detail="Schedule date cannot exceed 365 days")
    try:
        sessions = validate_sessions(body.sessions)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Every schedule writer uses this key. Sorted acquisition prevents two
    # overlapping ranges from deadlocking and makes validation + write atomic.
    for target_date in target_dates:
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
            {"k": f"schedule:{branch_uuid}:{doctor_uuid}:{target_date}"},
        )

    leaves = (
        await db.execute(
            select(DoctorUnavailability).where(
                DoctorUnavailability.branch_id == branch_uuid,
                DoctorUnavailability.doctor_id == doctor_uuid,
                DoctorUnavailability.date.in_(target_dates),
            )
        )
    ).scalars().all()
    confirmed = (
        await db.execute(
            select(Token).where(
                Token.branch_id == branch_uuid,
                Token.doctor_id == doctor_uuid,
                Token.date.in_(target_dates),
                Token.status == "confirmed",
            )
        )
    ).scalars().all()
    leave_dates = {row.date for row in leaves}
    confirmed_by_date: dict[date, list[Token]] = {}
    for token in confirmed:
        confirmed_by_date.setdefault(token.date, []).append(token)

    conflicts: dict[date, list[str]] = {}
    valid_slots = _date_slots(sessions, doctor.slot_duration_minutes)
    effective_limit = body.token_limit if body.token_limit is not None else doctor.daily_token_limit
    for target_date in target_dates:
        booked = confirmed_by_date.get(target_date, [])
        if sessions and target_date in leave_dates:
            conflicts.setdefault(target_date, []).append(
                "Doctor is marked on leave; remove leave before publishing sessions."
            )
        if doctor.booking_type == "appointment":
            invalid = [
                token for token in booked
                if token.appointment_time is None or token.appointment_time not in valid_slots
            ]
            if invalid:
                conflicts.setdefault(target_date, []).append(
                    f"Schedule would invalidate {len(invalid)} confirmed appointment(s)."
                )
        elif booked and not sessions:
            conflicts.setdefault(target_date, []).append(
                f"Schedule would invalidate {len(booked)} confirmed token booking(s)."
            )
        elif effective_limit is not None and len(booked) > effective_limit:
            conflicts.setdefault(target_date, []).append(
                f"Token limit cannot be below {len(booked)} already-confirmed patients."
            )

    if conflicts:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Schedule range has conflicts. No dates were changed.",
                "conflicts": [
                    {"date": target_date.isoformat(), "reasons": conflicts[target_date]}
                    for target_date in target_dates
                    if target_date in conflicts
                ],
            },
        )

    existing = (
        await db.execute(
            select(DoctorDateSchedule).where(
                DoctorDateSchedule.branch_id == branch_uuid,
                DoctorDateSchedule.doctor_id == doctor_uuid,
                DoctorDateSchedule.date.in_(target_dates),
            )
        )
    ).scalars().all()
    by_date = {row.date: row for row in existing}
    note = body.notes.strip() if body.notes and body.notes.strip() else None
    for target_date in target_dates:
        row = by_date.get(target_date)
        if row is None:
            row = DoctorDateSchedule(
                branch_id=branch_uuid,
                doctor_id=doctor_uuid,
                date=target_date,
                sessions=sessions,
            )
            db.add(row)
        row.sessions = sessions
        row.token_limit = body.token_limit
        row.notes = note
        row.updated_by_user_id = uuid.UUID(current_user.user_id)

    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    await invalidate_clinic_cache(branch_uuid)

    background_tasks.add_task(
        _sync_date_schedule_range_events,
        branch_uuid,
        doctor_uuid,
        target_dates,
    )

    request.state.audit_resource_id = doctor_id
    request.state.audit_user_id = current_user.user_id
    request.state.audit_branch_id = branch_id
    request.state.audit_metadata = {
        "doctor_id": doctor_id,
        "date_from": body.date_from.isoformat(),
        "date_to": body.date_to.isoformat(),
        "dates_published": len(target_dates),
        "sessions": sessions,
        "token_limit": body.token_limit,
    }
    return DateScheduleRangeOut(schedules=[
        DateScheduleOut(
            date=target_date.isoformat(),
            status="available" if sessions else "unavailable",
            source="date_override",
            sessions=sessions,
            token_limit=body.token_limit if body.token_limit is not None else doctor.daily_token_limit,
            notes=note,
            is_published=True,
        )
        for target_date in target_dates
    ])

@router.put(
    "/{branch_id}/{doctor_id}/schedule/{date_str}",
    response_model=DateScheduleOut,
)
@audit("availability.schedule_publish", resource_type="doctor_date_schedule")
async def publish_date_schedule(
    branch_id: str,
    doctor_id: str,
    date_str: str,
    body: DateScheduleIn,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DateScheduleOut:
    """Idempotently publish exact sessions for one date.

    The edit is rejected if it would invalidate a confirmed appointment or
    reduce a token limit below the confirmed patient count. No silent patient
    cancellation is permitted from a schedule edit.
    """
    await assert_branch_access(current_user, branch_id, db)
    try:
        branch_uuid = uuid.UUID(branch_id)
        doctor_uuid = uuid.UUID(doctor_id)
        target_date = date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID or date format")

    # Keep exact-date validation on the same doctor configuration snapshot as
    # booking confirmation and range publication.
    await db.execute(
        text("SELECT pg_advisory_xact_lock_shared(hashtextextended(:k, 0))"),
        {"k": f"schedule-config:{branch_uuid}:{doctor_uuid}"},
    )

    doctor = (
        await db.execute(
            select(Doctor).where(
                Doctor.id == doctor_uuid,
                Doctor.branch_id == branch_uuid,
                Doctor.status == "active",
            )
        )
    ).scalar_one_or_none()
    if doctor is None:
        raise HTTPException(status_code=404, detail="Doctor not found")
    _schedule_writer_allowed(current_user, doctor)

    from backend.routers.queue import _branch_today
    branch_today = await _branch_today(branch_uuid, db)
    if target_date < branch_today:
        raise HTTPException(status_code=422, detail="Cannot change a past schedule")
    if target_date > branch_today + timedelta(days=365):
        raise HTTPException(status_code=422, detail="Schedule date cannot exceed 365 days")
    try:
        sessions = validate_sessions(body.sessions)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Same lock as confirm_booking and leave publication. It must be acquired
    # before checking leave/bookings so neither can change under this edit.
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
        {"k": f"schedule:{branch_uuid}:{doctor_uuid}:{target_date}"},
    )
    if sessions and (
        await db.execute(
            select(DoctorUnavailability.id).where(
                DoctorUnavailability.branch_id == branch_uuid,
                DoctorUnavailability.doctor_id == doctor_uuid,
                DoctorUnavailability.date == target_date,
            )
        )
    ).scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=409,
            detail="Doctor is marked on leave that date. Remove leave before publishing sessions.",
        )

    confirmed = (
        await db.execute(
            select(Token).where(
                Token.branch_id == branch_uuid,
                Token.doctor_id == doctor_uuid,
                Token.date == target_date,
                Token.status == "confirmed",
            )
        )
    ).scalars().all()
    if doctor.booking_type == "appointment":
        valid_slots = _date_slots(sessions, doctor.slot_duration_minutes)
        invalid = [
            token for token in confirmed
            if token.appointment_time is None or token.appointment_time not in valid_slots
        ]
        if invalid:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Schedule would invalidate {len(invalid)} confirmed appointment(s). "
                    "Reschedule or cancel those appointments first."
                ),
            )
    else:
        if confirmed and not sessions:
            raise HTTPException(
                status_code=409,
                detail=f"Schedule would invalidate {len(confirmed)} confirmed token booking(s).",
            )
        effective_limit = body.token_limit if body.token_limit is not None else doctor.daily_token_limit
        if effective_limit is not None and len(confirmed) > effective_limit:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Token limit cannot be below {len(confirmed)} already-confirmed patients."
                ),
            )

    row = (
        await db.execute(
            select(DoctorDateSchedule).where(
                DoctorDateSchedule.branch_id == branch_uuid,
                DoctorDateSchedule.doctor_id == doctor_uuid,
                DoctorDateSchedule.date == target_date,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = DoctorDateSchedule(
            branch_id=branch_uuid,
            doctor_id=doctor_uuid,
            date=target_date,
            sessions=sessions,
        )
        db.add(row)
    row.sessions = sessions
    row.token_limit = body.token_limit
    row.notes = body.notes.strip() if body.notes and body.notes.strip() else None
    row.updated_by_user_id = uuid.UUID(current_user.user_id)
    await db.commit()
    await invalidate_clinic_cache(branch_uuid)

    # Publish this day's sessions to the clinic calendar.
    #
    # This endpoint never touched Google Calendar, so a doctor who publishes
    # next week's plan — the whole reason date-specific schedules exist —
    # changed nothing the clinic could see there (Vinay 2026-08-04). RULE 4
    # discipline: best-effort, and a calendar failure never fails the publish
    # that has already committed above.
    try:
        from backend.services.doctor_calendar import sync_date_schedule_events

        await sync_date_schedule_events(db, branch_uuid, doctor_uuid, target_date)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "date_schedule_calendar_sync_failed",
            branch_id=branch_id, doctor_id=doctor_id, error=str(exc)[:200],
        )

    request.state.audit_resource_id = str(row.id)
    request.state.audit_user_id = current_user.user_id
    request.state.audit_branch_id = branch_id
    request.state.audit_metadata = {
        "doctor_id": doctor_id,
        "date": date_str,
        "sessions": sessions,
        "token_limit": body.token_limit,
    }
    return DateScheduleOut(
        date=date_str,
        status="available" if sessions else "unavailable",
        source="date_override",
        sessions=sessions,
        token_limit=row.token_limit if row.token_limit is not None else doctor.daily_token_limit,
        notes=row.notes,
        is_published=True,
    )


@router.get(
    "/{branch_id}/{doctor_id}/schedule",
    response_model=list[DateScheduleOut],
)
async def list_date_schedules(
    branch_id: str,
    doctor_id: str,
    from_: str = Query(..., alias="from"),
    to: str = Query(...),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[DateScheduleOut]:
    """Return resolved truth for every date, including unpublished dates."""
    await assert_branch_access(current_user, branch_id, db)
    try:
        branch_uuid = uuid.UUID(branch_id)
        doctor_uuid = uuid.UUID(doctor_id)
        date_from = date.fromisoformat(from_)
        date_to = date.fromisoformat(to)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID or date format")
    if date_from > date_to or (date_to - date_from).days > 93:
        raise HTTPException(status_code=422, detail="Schedule range must be 0 to 93 days")

    doctor = (
        await db.execute(
            select(Doctor).where(
                Doctor.id == doctor_uuid,
                Doctor.branch_id == branch_uuid,
                Doctor.status == "active",
            )
        )
    ).scalar_one_or_none()
    if doctor is None:
        raise HTTPException(status_code=404, detail="Doctor not found")

    rows = (
        await db.execute(
            select(DoctorDateSchedule).where(
                DoctorDateSchedule.branch_id == branch_uuid,
                DoctorDateSchedule.doctor_id == doctor_uuid,
                DoctorDateSchedule.date >= date_from,
                DoctorDateSchedule.date <= date_to,
            )
        )
    ).scalars().all()
    leaves = (
        await db.execute(
            select(DoctorUnavailability).where(
                DoctorUnavailability.branch_id == branch_uuid,
                DoctorUnavailability.doctor_id == doctor_uuid,
                DoctorUnavailability.date >= date_from,
                DoctorUnavailability.date <= date_to,
            )
        )
    ).scalars().all()
    by_date = {row.date: row for row in rows}
    leave_by_date = {row.date: row for row in leaves}
    recurring = effective_recurring_schedule(doctor)

    result: list[DateScheduleOut] = []
    current = date_from
    while current <= date_to:
        row = by_date.get(current)
        leave = leave_by_date.get(current)
        if leave is not None:
            sessions, status, source, published = [], "unavailable", "leave", True
            token_limit, notes = None, leave.reason
        elif row is not None:
            sessions = validate_sessions(row.sessions)
            status, source, published = ("available" if sessions else "unavailable"), "date_override", True
            token_limit = row.token_limit if row.token_limit is not None else doctor.daily_token_limit
            notes = row.notes
        elif doctor.schedule_mode == "date_specific":
            sessions, status, source, published = [], "unpublished", "unpublished", False
            token_limit, notes = None, None
        elif not recurring:
            sessions, status, source, published = [], "unpublished", "unpublished", False
            token_limit, notes = None, None
        else:
            sessions = recurring.get(str(current.weekday()), [])
            status, source, published = ("available" if sessions else "unavailable"), "recurring", False
            token_limit, notes = doctor.daily_token_limit, None
        result.append(DateScheduleOut(
            date=current.isoformat(), status=status, source=source,
            sessions=sessions, token_limit=token_limit, notes=notes,
            is_published=published,
        ))
        current += timedelta(days=1)
    return result


@router.delete(
    "/{branch_id}/{doctor_id}/schedule/{date_str}",
    status_code=204,
)
@audit("availability.schedule_unpublish", resource_type="doctor_date_schedule")
async def delete_date_schedule(
    branch_id: str,
    doctor_id: str,
    date_str: str,
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete an override only when it cannot invalidate confirmed bookings."""
    await assert_branch_access(current_user, branch_id, db)
    try:
        branch_uuid = uuid.UUID(branch_id)
        doctor_uuid = uuid.UUID(doctor_id)
        target_date = date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID or date format")
    doctor = (
        await db.execute(select(Doctor).where(
            Doctor.id == doctor_uuid, Doctor.branch_id == branch_uuid,
        ))
    ).scalar_one_or_none()
    if doctor is None:
        raise HTTPException(status_code=404, detail="Doctor not found")
    _schedule_writer_allowed(current_user, doctor)
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
        {"k": f"schedule:{branch_uuid}:{doctor_uuid}:{target_date}"},
    )
    confirmed_count = (
        await db.execute(select(func.count()).select_from(Token).where(
            Token.branch_id == branch_uuid, Token.doctor_id == doctor_uuid,
            Token.date == target_date, Token.status == "confirmed",
        ))
    ).scalar_one()
    if confirmed_count:
        raise HTTPException(
            status_code=409,
            detail="Cannot unpublish a date with confirmed bookings.",
        )
    row = (
        await db.execute(select(DoctorDateSchedule).where(
            DoctorDateSchedule.branch_id == branch_uuid,
            DoctorDateSchedule.doctor_id == doctor_uuid,
            DoctorDateSchedule.date == target_date,
        ))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Published schedule not found")
    row_id = str(row.id)
    await db.delete(row)
    await db.commit()
    await invalidate_clinic_cache(branch_uuid)
    background_tasks.add_task(
        _sync_date_schedule_range_events,
        branch_uuid,
        doctor_uuid,
        [target_date],
    )
    request.state.audit_resource_id = row_id
    request.state.audit_user_id = current_user.user_id
    request.state.audit_branch_id = branch_id
    request.state.audit_metadata = {
        "doctor_id": doctor_id,
        "date": date_str,
    }
    await invalidate_clinic_cache(branch_uuid)

@router.post(
    "/{branch_id}/{doctor_id}",
    response_model=MarkUnavailableResponse,
    status_code=200,
)
@audit("availability.mark_unavailable", resource_type="doctor_unavailability")
async def mark_unavailable(
    branch_id: str,
    doctor_id: str,
    body: MarkUnavailableRequest,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    _staff: CurrentUser = Depends(_require_staff),
    _rate: None = Depends(availability_post_limit),
    db: AsyncSession = Depends(get_db),
) -> MarkUnavailableResponse:
    """Mark a doctor unavailable for [date_from, date_to] (inclusive).

    Cascade flow (single DB transaction):
      1. INSERT DoctorUnavailability per date — ON CONFLICT DO NOTHING.
      2. SELECT + lock confirmed tokens in range.
      3. Cancel each token (status='cancelled_by_clinic').
      4. INSERT FollowupTask(task_type='cascade_rebook') per cancelled token.
    Then best-effort: enqueue CalendarWriteTask(operation='delete') for each
    cancelled slot-doctor token with a google_calendar_event_id.

    Audit:
      - availability.mark_unavailable (this route)
      - availability.cascade_cancel   (one row per cancelled token, below)
    """
    await assert_branch_access(current_user, branch_id, db)

    if body.date_from > body.date_to:
        raise HTTPException(
            status_code=422,
            detail="date_from must be <= date_to",
        )

    try:
        branch_uuid = uuid.UUID(branch_id)
        doctor_uuid = uuid.UUID(doctor_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format")

    # M10: never cascade a PAST date — that cancels yesterday's already-done
    # bookings and schedules rebook calls about a day that's gone, while today's
    # real bookings for an absent doctor stay live. "Today" in the branch tz.
    from backend.routers.queue import _branch_today

    branch_today = await _branch_today(branch_uuid, db)
    if body.date_to < branch_today:
        raise HTTPException(
            status_code=422, detail="Cannot mark leave for a date already in the past"
        )
    # L3: bound the range — date_from=2026..date_to=2126 would INSERT ~36,500
    # rows in one transaction (authenticated-staff DoS / table spam).
    if (body.date_to - body.date_from).days > 365:
        raise HTTPException(status_code=422, detail="Leave range cannot exceed 365 days")

    # Verify doctor belongs to this branch (Rule 1 ownership check)
    doctor_result = await db.execute(
        select(Doctor).where(
            Doctor.id == doctor_uuid,
            Doctor.branch_id == branch_uuid,    # Rule 1 — mandatory
        )
    )
    doctor = doctor_result.scalar_one_or_none()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")

    # B9: the token cascade must never touch PAST-dated bookings even when the
    # leave range starts before today (M10 only rejected ranges ENTIRELY in the
    # past). Clamp the cancel lower bound to branch-local today; unavailability
    # rows still cover the full requested range.
    cancel_from = max(body.date_from, branch_today)

    # Capture what will be cancelled for per-token audit rows (before cascade)
    # Lock every affected doctor/date before inserting leave or cancelling.
    # This serializes leave with exact-date publication and final booking.
    lock_date = cancel_from
    while lock_date <= body.date_to:
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
            {"k": f"schedule:{branch_uuid}:{doctor_uuid}:{lock_date}"},
        )
        lock_date += timedelta(days=1)

    pre_tokens_result = await db.execute(
        select(Token).where(
            Token.branch_id == branch_uuid,     # Rule 1 — mandatory
            Token.doctor_id == doctor_uuid,
            Token.date >= cancel_from,          # B9: match the cascade's clamp
            Token.date <= body.date_to,
            Token.status == "confirmed",
        )
    )
    pre_tokens = [
        {"id": str(t.id), "date": t.date.isoformat()}
        for t in pre_tokens_result.scalars().all()
    ]

    counts = await cascade_for_unavailability(
        db=db,
        branch_id=branch_uuid,
        doctor_id=doctor_uuid,
        date_from=body.date_from,
        date_to=body.date_to,
        user_id=current_user.user_id,
        reason=body.reason,
        min_cancel_date=branch_today,  # B9
    )

    logger.info(
        "availability_marked",
        branch_id=branch_id,
        doctor_id=doctor_id,
        date_from=body.date_from.isoformat(),
        date_to=body.date_to.isoformat(),
        cancelled_tokens=counts["cancelled_tokens"],
        user_id=current_user.user_id,
    )

    # Set audit context for @audit decorator (mark_unavailable event)
    # PII denylist: no patient names/phones — doctor_id + dates only
    request.state.audit_resource_id = doctor_id
    request.state.audit_user_id = current_user.user_id
    request.state.audit_branch_id = branch_id
    request.state.audit_metadata = {
        "date_from": body.date_from.isoformat(),
        "date_to": body.date_to.isoformat(),
        "doctor_id": doctor_id,
    }

    # Write one cascade_cancel audit row per cancelled token
    # (outside the main transaction — best-effort; audit failure never blocks)
    for tok in pre_tokens:
        try:
            await write_audit_row(
                action="availability.cascade_cancel",
                resource_type="token",
                resource_id=tok["id"],
                user_id=uuid.UUID(current_user.user_id),
                branch_id=branch_uuid,
                metadata={
                    "token_id": tok["id"],
                    "doctor_id": doctor_id,
                    "date": tok["date"],
                },
                success=True,
            )
        except Exception as audit_exc:
            logger.error(
                "cascade_cancel_audit_failed",
                token_id=tok["id"],
                error=str(audit_exc),
            )

    return MarkUnavailableResponse(
        unavailable_dates=counts["unavailable_dates"],
        cancelled_tokens=counts["cancelled_tokens"],
        followups_scheduled=counts["followups_scheduled"],
    )


@router.get(
    "/{branch_id}/{doctor_id}/affected",
    response_model=AffectedTokensResponse,
)
async def get_affected_tokens(
    branch_id: str,
    doctor_id: str,
    from_: str = Query(..., alias="from"),
    to: str = Query(...),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AffectedTokensResponse:
    """Preflight: list confirmed tokens that WOULD be cancelled for the date range.

    Does NOT cancel anything. Used by the frontend drawer to show impact before
    the org_admin confirms.

    PII: returns patient_first_name + last-4 digits of phone.
    Access: receptionist + org_admin (both have branch access and DPDP permission
    to see patient booking details).
    """
    await assert_branch_access(current_user, branch_id, db)

    date_from = _parse_date(from_, "from")
    date_to = _parse_date(to, "to")

    if date_from > date_to:
        raise HTTPException(status_code=422, detail="from must be <= to")

    try:
        branch_uuid = uuid.UUID(branch_id)
        doctor_uuid = uuid.UUID(doctor_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format")

    # Verify doctor belongs to this branch (Rule 1)
    doc_result = await db.execute(
        select(Doctor).where(
            Doctor.id == doctor_uuid,
            Doctor.branch_id == branch_uuid,    # Rule 1 — mandatory
        )
    )
    if not doc_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Doctor not found")

    # Fetch tokens with patient join — all within branch scope
    token_result = await db.execute(
        select(Token, Patient)
        .join(Patient, Token.patient_id == Patient.id)
        .where(
            Token.branch_id == branch_uuid,     # Rule 1 — mandatory
            Token.doctor_id == doctor_uuid,
            Token.date >= date_from,
            Token.date <= date_to,
            Token.status == "confirmed",
        )
        .order_by(Token.date, Token.token_number)
    )
    rows = token_result.all()

    # Capture values inside session block (DetachedInstanceError prevention)
    affected: list[AffectedToken] = []
    for token, patient in rows:
        phone_last4 = patient.phone[-4:] if patient.phone and len(patient.phone) >= 4 else None
        first_name = patient.name.split()[0] if patient.name else "Unknown"
        affected.append(
            AffectedToken(
                token_id=str(token.id),
                token_number=token.token_number,
                date=token.date.isoformat(),
                appointment_time=(
                    token.appointment_time.strftime("%H:%M")
                    if token.appointment_time else None
                ),
                patient_first_name=first_name,
                patient_phone_last4=phone_last4,
            )
        )

    logger.info(
        "affected_tokens_preflight",
        branch_id=branch_id,
        doctor_id=doctor_id,
        date_from=date_from.isoformat(),
        date_to=date_to.isoformat(),
        count=len(affected),
        user_id=current_user.user_id,
    )

    return AffectedTokensResponse(count=len(affected), tokens=affected)


@router.get(
    "/{branch_id}/{doctor_id}",
    response_model=list[UnavailabilityRow],
)
async def list_unavailability(
    branch_id: str,
    doctor_id: str,
    from_: str = Query(..., alias="from"),
    to: str = Query(...),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[UnavailabilityRow]:
    """List DoctorUnavailability rows for [from, to] date range (inclusive).

    Roles: receptionist + org_admin.
    """
    await assert_branch_access(current_user, branch_id, db)

    date_from = _parse_date(from_, "from")
    date_to = _parse_date(to, "to")

    try:
        branch_uuid = uuid.UUID(branch_id)
        doctor_uuid = uuid.UUID(doctor_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format")

    result = await db.execute(
        select(DoctorUnavailability)
        .where(
            DoctorUnavailability.branch_id == branch_uuid,   # Rule 1 — mandatory
            DoctorUnavailability.doctor_id == doctor_uuid,
            DoctorUnavailability.date >= date_from,
            DoctorUnavailability.date <= date_to,
        )
        .order_by(DoctorUnavailability.date)
    )
    rows = result.scalars().all()

    # Capture values while session open (DetachedInstanceError pattern)
    out = [_unavail_to_out(r) for r in rows]

    logger.info(
        "unavailability_listed",
        branch_id=branch_id,
        doctor_id=doctor_id,
        count=len(out),
        user_id=current_user.user_id,
    )
    return out


@router.delete(
    "/{branch_id}/{doctor_id}/{date_str}",
    status_code=204,
)
@audit("availability.remove", resource_type="doctor_unavailability")
async def remove_unavailability(
    branch_id: str,
    doctor_id: str,
    date_str: str,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    _staff: CurrentUser = Depends(_require_staff),  # L9: same role can undo
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove a single unavailability date row.

    Does NOT un-cancel existing cancelled tokens. The tokens remain cancelled;
    the org_admin must manually re-book affected patients via followup tasks.
    Role: org_admin only.
    """
    await assert_branch_access(current_user, branch_id, db)

    try:
        target_date = date.fromisoformat(date_str)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid date format '{date_str}' — expected YYYY-MM-DD",
        )

    try:
        branch_uuid = uuid.UUID(branch_id)
        doctor_uuid = uuid.UUID(doctor_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format")

    result = await db.execute(
        select(DoctorUnavailability).where(
            DoctorUnavailability.branch_id == branch_uuid,   # Rule 1 — mandatory
            DoctorUnavailability.doctor_id == doctor_uuid,
            DoctorUnavailability.date == target_date,
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Unavailability date not found")

    row_id = str(row.id)
    await db.delete(row)
    await db.commit()

    logger.info(
        "unavailability_removed",
        branch_id=branch_id,
        doctor_id=doctor_id,
        date=date_str,
        user_id=current_user.user_id,
    )

    # Audit context for @audit decorator
    # PII denylist: no patient names/phones
    request.state.audit_resource_id = row_id
    request.state.audit_user_id = current_user.user_id
    request.state.audit_branch_id = branch_id
    request.state.audit_metadata = {
        "date": date_str,
        "doctor_id": doctor_id,
    }


@router.get("/{branch_id}/leave/upcoming")
async def upcoming_leave(
    branch_id: str,
    days: int = 30,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """All doctors on leave from today through today+days (default 30),
    grouped into consecutive from-to ranges (Vinay 2026-07-15). RULE 1
    branch-scoped; read-only. Roles: receptionist + org_admin."""
    from datetime import timedelta as _td

    from backend.routers.queue import _branch_today

    await assert_branch_access(current_user, branch_id, db)
    try:
        branch_uuid = uuid.UUID(branch_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid branch_id")

    today = await _branch_today(branch_uuid, db)
    end = today + _td(days=days)

    rows = (
        await db.execute(
            select(DoctorUnavailability.doctor_id, DoctorUnavailability.date, Doctor.name)
            .join(Doctor, Doctor.id == DoctorUnavailability.doctor_id)
            .where(
                DoctorUnavailability.branch_id == branch_uuid,  # RULE 1
                DoctorUnavailability.date >= today,
                DoctorUnavailability.date <= end,
            )
            .order_by(Doctor.name, DoctorUnavailability.date)
        )
    ).all()

    # Group consecutive dates per doctor into [from, to] ranges.
    ranges: list[dict] = []
    cur_doc = None
    cur_name = None
    run_start = None
    prev = None
    for doctor_id, d, name in rows:
        if doctor_id != cur_doc or (prev is not None and (d - prev).days > 1):
            if run_start is not None:
                ranges.append({
                    "doctor_name": cur_name,
                    "from": run_start.isoformat(),
                    "to": prev.isoformat(),
                })
            cur_doc, cur_name, run_start = doctor_id, name, d
        prev = d
        cur_name = name
    if run_start is not None:
        ranges.append({
            "doctor_name": cur_name, "from": run_start.isoformat(), "to": prev.isoformat(),
        })

    return {"leave": ranges, "days": days}

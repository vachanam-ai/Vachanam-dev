"""Receptionist queue endpoints.

All routes:
- Require JWT (via Depends(get_current_user))
- Enforce branch_id from URL is in the user's branch_ids JWT claim (via assert_branch_access)
- Filter every DB query by branch_id (CLAUDE.md Rule 1 — final tripwire)

Per CLAUDE.md Rule 1: branch isolation is enforced at THREE layers — middleware
(branch_guard), route handler (the user's JWT branch_ids), and DB query
(WHERE branch_id = ?). Any single layer failure must not breach data.
"""
import uuid
from datetime import date, datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.middleware.auth_middleware import CurrentUser, get_current_user
from backend.middleware.branch_guard import assert_branch_access
from backend.middleware.rate_limit import queue_today_limit
from backend.models.schema import Doctor, Patient, Token
from backend.services.audit_service import audit

logger = structlog.get_logger()
router = APIRouter()


class PatientEntry(BaseModel):
    appointment_id: str
    token_number: int | None
    patient_name: str
    status: str
    is_urgent: bool
    confirmed_at: str | None


class DoctorEntry(BaseModel):
    doctor_id: str
    doctor_name: str
    booking_type: str
    stats: dict
    patients: list[PatientEntry]


class QueueSummary(BaseModel):
    total: int
    attended: int
    no_show: int
    remaining: int


class QueueResponse(BaseModel):
    date: str
    branch_id: str
    summary: QueueSummary
    doctors: list[DoctorEntry]


@router.get(
    "/{branch_id}/today",
    response_model=QueueResponse,
    dependencies=[Depends(queue_today_limit)],
)
async def get_today_queue(
    branch_id: str,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> QueueResponse:
    """Today's complete queue grouped by doctor.

    Returns ALL tokens for the branch dated today with status in
    (confirmed, attended, no_show). Sorted by doctor name then token number.

    Performance: this hits Token (filtered by branch_id + date) joined to Patient
    and Doctor. With TD-018 indexes added, this is a single index scan.
    Without indexes (current state), it's a seq scan — fine for MVP scale.
    """
    await assert_branch_access(current_user, branch_id, db)

    try:
        branch_uuid = uuid.UUID(branch_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid branch_id format")

    today = date.today()

    try:
        result = await db.execute(
            select(Token, Patient, Doctor)
            .join(Patient, Token.patient_id == Patient.id)
            .join(Doctor, Token.doctor_id == Doctor.id)
            .where(
                Token.branch_id == branch_uuid,  # MANDATORY — final tripwire
                Token.date == today,
                Token.status.in_(["confirmed", "attended", "no_show"]),
            )
            .order_by(Doctor.name, Token.token_number)
        )
        rows = result.all()
    except Exception as exc:
        # Catches SQLAlchemy errors (table missing, query fail) and lower-level
        # asyncpg/asyncio transport errors that bubble up through the SQLAlchemy
        # session (e.g., proactor event loop errors during concurrent connection
        # pool pings on Windows/Python 3.14).  Any unhandled exception here must
        # become an HTTP 500 — not propagate through Starlette's ServerErrorMiddleware
        # which would re-raise and cause httpx.ASGITransport to propagate the
        # exception to test callers (breaking the rate-limit test assertions).
        logger.error("queue_db_error", branch_id=branch_id, error=str(exc))
        raise HTTPException(status_code=500, detail="Database error")

    doctors_map: dict[str, DoctorEntry] = {}
    summary_attended = 0
    summary_no_show = 0
    summary_remaining = 0

    for token, patient, doctor in rows:
        did = str(doctor.id)
        if did not in doctors_map:
            doctors_map[did] = DoctorEntry(
                doctor_id=did,
                doctor_name=doctor.name,
                booking_type=doctor.booking_type,
                stats={"attended": 0, "no_show": 0, "remaining": 0},
                patients=[],
            )
        entry = doctors_map[did]
        entry.patients.append(
            PatientEntry(
                appointment_id=str(token.id),
                token_number=token.token_number,
                patient_name=patient.name,
                status=token.status,
                is_urgent=token.is_urgent,
                confirmed_at=token.confirmed_at.isoformat() if token.confirmed_at else None,
            )
        )
        if token.status == "attended":
            entry.stats["attended"] += 1
            summary_attended += 1
        elif token.status == "no_show":
            entry.stats["no_show"] += 1
            summary_no_show += 1
        else:  # confirmed
            entry.stats["remaining"] += 1
            summary_remaining += 1

    return QueueResponse(
        date=str(today),
        branch_id=branch_id,
        summary=QueueSummary(
            total=len(rows),
            attended=summary_attended,
            no_show=summary_no_show,
            remaining=summary_remaining,
        ),
        doctors=list(doctors_map.values()),
    )


class StatusResponse(BaseModel):
    status: str
    token_id: str


@router.patch(
    "/{branch_id}/token/{token_id}/attend",
    response_model=StatusResponse,
    dependencies=[Depends(queue_today_limit)],
)
@audit("token.attend", resource_type="token")
async def mark_attended(
    branch_id: str,
    token_id: str,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StatusResponse:
    """Mark a patient as attended (showed up + seen by doctor).

    Sets audit context on request.state so the @audit decorator can capture
    resource_id, user_id, and branch_id for the audit_log row.
    """
    await assert_branch_access(current_user, branch_id, db)
    result = await _update_status(db, token_id, branch_id, "attended", current_user.user_id)
    # Set audit context AFTER success — decorator reads this in its finally block
    request.state.audit_resource_id = token_id
    request.state.audit_user_id = current_user.user_id
    request.state.audit_branch_id = branch_id
    return result


@router.patch(
    "/{branch_id}/token/{token_id}/no-show",
    response_model=StatusResponse,
    dependencies=[Depends(queue_today_limit)],
)
@audit("token.no_show", resource_type="token")
async def mark_no_show(
    branch_id: str,
    token_id: str,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StatusResponse:
    """Mark a patient as no-show (slot missed).

    Sets audit context on request.state so the @audit decorator can capture
    resource_id, user_id, and branch_id for the audit_log row.
    """
    await assert_branch_access(current_user, branch_id, db)
    result = await _update_status(db, token_id, branch_id, "no_show", current_user.user_id)
    # Set audit context AFTER success — decorator reads this in its finally block
    request.state.audit_resource_id = token_id
    request.state.audit_user_id = current_user.user_id
    request.state.audit_branch_id = branch_id
    return result


async def _update_status(
    db: AsyncSession,
    token_id: str,
    branch_id: str,
    new_status: str,
    user_id: str,
) -> StatusResponse:
    """Shared helper for attend/no-show. Enforces:
    - token belongs to the given branch (defence-in-depth — guard already ran)
    - token is not already in a terminal state (409 to prevent silent double-update)
    """
    try:
        token_uuid = uuid.UUID(token_id)
        branch_uuid = uuid.UUID(branch_id)
        user_uuid = uuid.UUID(user_id) if user_id else None
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format")

    try:
        result = await db.execute(
            select(Token).where(
                Token.id == token_uuid,
                Token.branch_id == branch_uuid,  # MANDATORY — final tripwire
            )
        )
        token = result.scalar_one_or_none()
    except SQLAlchemyError as exc:
        logger.error(
            "token_status_db_error",
            token_id=token_id,
            branch_id=branch_id,
            error=str(exc),
        )
        raise HTTPException(status_code=500, detail="Database error")
    if not token:
        raise HTTPException(status_code=404, detail="Token not found")
    if token.status in ("attended", "no_show", "cancelled_by_clinic"):
        raise HTTPException(status_code=409, detail=f"Already {token.status}")

    token.status = new_status
    token.attended_at = datetime.now(timezone.utc)
    token.marked_by_user_id = user_uuid
    await db.commit()

    logger.info(
        "token_status_updated",
        token_id=token_id,
        new_status=new_status,
        branch_id=branch_id,
        marked_by_user_id=user_id,
    )
    return StatusResponse(status=new_status, token_id=token_id)


# ── Walk-in registration (receptionist desk) ─────────────────────────────────


class WalkInRequest(BaseModel):
    doctor_id: str
    patient_name: str
    patient_phone: str | None = None
    complaint: str | None = None
    appointment_time: str | None = None  # "HH:MM", slot-doctors only
    is_urgent: bool = False


class WalkInResponse(BaseModel):
    token_id: str
    token_number: int | None
    appointment_time: str | None
    doctor_name: str
    patient_name: str
    booking_type: str


@router.post(
    "/{branch_id}/walkin",
    response_model=WalkInResponse,
    status_code=201,
    dependencies=[Depends(queue_today_limit)],
)
@audit("token.walkin_created", resource_type="token")
async def create_walkin(
    branch_id: str,
    body: WalkInRequest,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WalkInResponse:
    """Register a walk-in patient for today.

    Token-doctor: atomically assigns the next token (Redis INCR — Rule 2).
    Slot-doctor: books the given HH:MM slot (per-slot Redis key, same atomicity).
    Calendar write is hybrid (Rule 4 via booking_calendar): slot-doctor inline
    with retries, token-doctor enqueued — a walk-in at the desk never blocks
    on Google.
    """
    from datetime import time as time_cls

    from agent.tools.booking_tools import assign_token as _assign_token
    from backend.services.booking_calendar import write_booking_calendar

    await assert_branch_access(current_user, branch_id, db)
    branch_uuid = uuid.UUID(branch_id)
    doctor_uuid = uuid.UUID(body.doctor_id)
    today = date.today()

    # Doctor must belong to THIS branch and be active (Rule 1)
    result = await db.execute(
        select(Doctor).where(Doctor.id == doctor_uuid, Doctor.branch_id == branch_uuid)
    )
    doctor = result.scalar_one_or_none()
    if doctor is None or doctor.status != "active":
        raise HTTPException(status_code=404, detail="Doctor not found in this branch")
    if doctor.booking_type == "token" and doctor.walkins_closed_today_date == today:
        raise HTTPException(status_code=409, detail="Walk-ins are closed for this doctor today")

    appt_time: "time_cls | None" = None
    if body.appointment_time:
        try:
            appt_time = time_cls.fromisoformat(body.appointment_time)
        except ValueError:
            raise HTTPException(status_code=422, detail="appointment_time must be HH:MM")
    if doctor.booking_type == "appointment" and appt_time is None:
        raise HTTPException(status_code=422, detail="appointment_time required for this doctor")

    assignment = await _assign_token(
        doctor_id=doctor_uuid,
        branch_id=branch_uuid,
        booking_date=today,
        db=db,
        appointment_time=appt_time,
    )
    if not assignment.get("success"):
        reason = assignment.get("reason", "unavailable")
        status = 409 if reason in ("full", "slot_taken") else 422
        raise HTTPException(status_code=status, detail=f"Could not book: {reason}")

    # Patient: reuse by (branch, phone) when phone given; else fresh row (Rule 1)
    patient = None
    if body.patient_phone:
        result = await db.execute(
            select(Patient).where(
                Patient.branch_id == branch_uuid, Patient.phone == body.patient_phone
            )
        )
        patient = result.scalars().first()
    if patient is None:
        patient = Patient(
            branch_id=branch_uuid, name=body.patient_name, phone=body.patient_phone
        )
        db.add(patient)
        await db.flush()

    token = Token(
        branch_id=branch_uuid,
        doctor_id=doctor_uuid,
        patient_id=patient.id,
        date=today,
        token_number=assignment.get("token_number"),
        appointment_time=appt_time,
        source="walk_in",
        status="confirmed",
        is_urgent=body.is_urgent,
        confirmed_at=datetime.now(timezone.utc),
        marked_by_user_id=uuid.UUID(current_user.user_id),
    )
    db.add(token)
    await db.commit()
    await db.refresh(token)

    # Hybrid calendar write — never fails the walk-in (Rule 4 handled inside)
    result = await db.execute(select(Doctor).where(Doctor.id == doctor_uuid))
    doctor = result.scalar_one()
    from backend.models.schema import Branch as _Branch

    branch_row = (
        await db.execute(select(_Branch).where(_Branch.id == branch_uuid))
    ).scalar_one()
    await write_booking_calendar(
        db,
        token,
        doctor,
        doctor.google_calendar_id or branch_row.google_calendar_id,
        patient_first_name=body.patient_name.split()[0] if body.patient_name else "",
        patient_phone_last4=(body.patient_phone or "")[-4:],
    )

    request.state.audit_resource_id = str(token.id)
    request.state.audit_user_id = current_user.user_id
    request.state.audit_branch_id = branch_id

    logger.info(
        "walkin_created",
        branch_id=branch_id,
        doctor_id=body.doctor_id,
        token_number=token.token_number,
        via="walk_in",
    )
    return WalkInResponse(
        token_id=str(token.id),
        token_number=token.token_number,
        appointment_time=body.appointment_time,
        doctor_name=doctor.name,
        patient_name=body.patient_name,
        booking_type=doctor.booking_type,
    )

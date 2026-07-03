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
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.middleware.auth_middleware import CurrentUser, get_current_user
from backend.middleware.branch_guard import assert_branch_access
from backend.middleware.rate_limit import _make_endpoint_limiter
from backend.models.schema import Doctor, DoctorUnavailability, Patient, Token
from backend.services.audit_service import audit, write_audit_row
from backend.services.cascade_cancel import cascade_for_unavailability

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


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

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

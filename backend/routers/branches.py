"""Branch settings endpoints (clinic-facing).

Rule 1: every query filters by branch_id; access enforced via assert_branch_access.
Currently: voice selection for the clinic's AI agent.
"""
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.middleware.auth_middleware import CurrentUser, get_current_user
from backend.middleware.branch_guard import assert_branch_access
from backend.middleware.rate_limit import queue_today_limit
from backend.models.schema import Branch
from backend.services.audit_service import audit

logger = structlog.get_logger()
router = APIRouter()

# Sarvam Bulbul v3 speakers offered to clinics (curated 2026-06-11 by Vinay)
ALLOWED_VOICES = ["rupali", "simran", "kavya", "ishita", "shreya", "suhani"]


class BranchSettings(BaseModel):
    branch_id: str
    name: str
    address: str | None = None
    city: str | None = None
    clinic_phone: str | None = None
    tts_voice: str
    did_number: str | None
    emergency_contact: str | None
    google_calendar_id: str | None = None
    allowed_voices: list[str]
    doctors_count: int = 0
    staff_count: int = 0
    did_wired: bool | None = None  # set on PATCH when DID trunk sync runs


async def _settings_payload(db: AsyncSession, branch: Branch, branch_id: str, did_wired: bool | None = None) -> BranchSettings:
    from sqlalchemy import func as _f

    from backend.models.schema import Doctor, User

    doctors_count = (
        await db.execute(
            select(_f.count()).select_from(Doctor).where(Doctor.branch_id == branch.id)
        )
    ).scalar_one()
    staff_count = (
        await db.execute(
            select(_f.count()).select_from(User).where(User.branch_ids.contains([branch_id]))
        )
    ).scalar_one()
    return BranchSettings(
        branch_id=branch_id,
        name=branch.name,
        address=branch.address,
        city=branch.city,
        clinic_phone=getattr(branch, "clinic_phone", None),
        tts_voice=getattr(branch, "tts_voice", "rupali"),
        did_number=branch.did_number,
        emergency_contact=branch.emergency_contact,
        google_calendar_id=branch.google_calendar_id,
        allowed_voices=ALLOWED_VOICES,
        doctors_count=doctors_count,
        staff_count=staff_count,
        did_wired=did_wired,
    )


class VoiceUpdate(BaseModel):
    tts_voice: str


@router.get(
    "/{branch_id}/settings",
    response_model=BranchSettings,
    dependencies=[Depends(queue_today_limit)],
)
async def get_branch_settings(
    branch_id: str,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BranchSettings:
    await assert_branch_access(current_user, branch_id, db)
    result = await db.execute(select(Branch).where(Branch.id == uuid.UUID(branch_id)))
    branch = result.scalar_one_or_none()
    if branch is None:
        raise HTTPException(status_code=404, detail="Branch not found")
    return await _settings_payload(db, branch, branch_id)


@router.patch(
    "/{branch_id}/voice",
    response_model=BranchSettings,
    dependencies=[Depends(queue_today_limit)],
)
@audit("branch.voice_changed", resource_type="branch")
async def update_branch_voice(
    branch_id: str,
    body: VoiceUpdate,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BranchSettings:
    """Set the clinic's AI voice. org_admin only — reception can't change the brand voice."""
    await assert_branch_access(current_user, branch_id, db)
    if current_user.role not in ("org_admin",):
        raise HTTPException(status_code=403, detail="Only the clinic owner can change the voice")
    if body.tts_voice not in ALLOWED_VOICES:
        raise HTTPException(status_code=422, detail=f"Voice must be one of {ALLOWED_VOICES}")

    result = await db.execute(select(Branch).where(Branch.id == uuid.UUID(branch_id)))
    branch = result.scalar_one_or_none()
    if branch is None:
        raise HTTPException(status_code=404, detail="Branch not found")

    branch.tts_voice = body.tts_voice
    await db.commit()

    request.state.audit_resource_id = branch_id
    request.state.audit_user_id = current_user.user_id
    request.state.audit_branch_id = branch_id

    logger.info("branch_voice_changed", branch_id=branch_id, voice=body.tts_voice)
    return await _settings_payload(db, branch, branch_id)


# ── Clinic details, calendar, team management (org_admin) ───────────────────


class BranchDetailsUpdate(BaseModel):
    name: str | None = None
    address: str | None = None
    city: str | None = None
    clinic_phone: str | None = None
    emergency_contact: str | None = None
    google_calendar_id: str | None = None
    did_number: str | None = None  # owner enters the purchased/assigned number


class StaffMember(BaseModel):
    user_id: str
    email: str
    name: str | None
    role: str


class StaffCreate(BaseModel):
    email: str
    name: str
    password: str
    role: str = "receptionist"
    doctor_id: str | None = None  # link a doctor-role login to its Doctor row (G5)


def _require_org_admin(current_user: CurrentUser) -> None:
    if current_user.role != "org_admin":
        raise HTTPException(status_code=403, detail="Only the clinic owner can do this")


@router.patch(
    "/{branch_id}/settings",
    response_model=BranchSettings,
    dependencies=[Depends(queue_today_limit)],
)
@audit("branch.settings_updated", resource_type="branch")
async def update_branch_settings(
    branch_id: str,
    body: BranchDetailsUpdate,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BranchSettings:
    """Update clinic details. org_admin only. Only provided fields change."""
    await assert_branch_access(current_user, branch_id, db)
    _require_org_admin(current_user)

    result = await db.execute(select(Branch).where(Branch.id == uuid.UUID(branch_id)))
    branch = result.scalar_one_or_none()
    if branch is None:
        raise HTTPException(status_code=404, detail="Branch not found")

    # SECURITY: a DID is a tenant's identity — the voice agent resolves the
    # branch (and therefore which clinic's patients/doctors/calendar are
    # touched) purely from the dialed number. If two branches shared a DID, a
    # clinic could intercept another clinic's calls. Reject a DID already owned
    # by a different branch. (DPDP cross-tenant breach prevention.)
    if body.did_number is not None and body.did_number.strip():
        from backend.services.validators import normalize_did

        new_did = normalize_did(body.did_number)  # M11: canonical E.164
        body.did_number = new_did  # so the setattr loop below stores the clean form
        clash = (
            await db.execute(
                select(Branch).where(
                    Branch.did_number == new_did, Branch.id != branch.id
                )
            )
        ).scalar_one_or_none()
        if clash is not None:
            logger.warning(
                "did_collision_blocked", branch_id=branch_id, did_last4=new_did[-4:]
            )
            raise HTTPException(
                status_code=409,
                detail="This number is already assigned to another clinic. "
                "Contact support if this is your number.",
            )

    old_did = branch.did_number  # capture before mutate (G9 trunk cleanup)
    for field in (
        "name", "address", "city", "clinic_phone",
        "emergency_contact", "google_calendar_id", "did_number",
    ):
        value = getattr(body, field)
        if value is not None:
            setattr(branch, field, value.strip() or None)
    await db.commit()

    # DID changed -> wire it into the LiveKit inbound trunk so calls route
    # immediately. Failure is reported in the response, never fails the save.
    did_wired: bool | None = None
    if body.did_number is not None and branch.did_number:
        from backend.services.livekit_sip import (
            remove_did_from_inbound_trunk,
            sync_did_to_inbound_trunk,
        )

        # G9: if the DID actually changed, pull the OLD number off the trunk
        # first so a future reassignment of it can't route into our system.
        if old_did and old_did != branch.did_number:
            await remove_did_from_inbound_trunk(old_did)

        sync = await sync_did_to_inbound_trunk(branch.did_number)
        did_wired = sync["ok"]
        if not sync["ok"]:
            logger.warning("did_wire_pending", branch_id=branch_id, detail=sync["detail"])

    request.state.audit_resource_id = branch_id
    request.state.audit_user_id = current_user.user_id
    request.state.audit_branch_id = branch_id
    logger.info("branch_settings_updated", branch_id=branch_id)

    return await _settings_payload(db, branch, branch_id, did_wired=did_wired)


@router.post(
    "/{branch_id}/calendar-test",
    dependencies=[Depends(queue_today_limit)],
)
async def test_calendar_connection(
    branch_id: str,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create + delete a probe event on the branch calendar. Proves the
    service account has writer access before any real booking depends on it."""
    await assert_branch_access(current_user, branch_id, db)
    result = await db.execute(select(Branch).where(Branch.id == uuid.UUID(branch_id)))
    branch = result.scalar_one_or_none()
    if branch is None or not branch.google_calendar_id:
        raise HTTPException(status_code=422, detail="Set a calendar ID first")

    from backend.services.calendar_service import GoogleCalendarService

    try:
        svc = GoogleCalendarService()
        ok = await _probe_calendar(svc, branch.google_calendar_id)
    except Exception as e:
        logger.warning("calendar_test_failed", branch_id=branch_id, error=str(e))
        return {"ok": False, "detail": str(e)[:200]}
    return {"ok": ok}


async def _probe_calendar(svc, calendar_id: str) -> bool:
    """Insert + delete a 1-minute probe event (sync client run in thread)."""
    import asyncio as _asyncio
    from datetime import datetime, timedelta, timezone as _tz

    def _probe() -> bool:
        start = datetime.now(_tz.utc) + timedelta(days=1)
        ev = (
            svc._service.events()
            .insert(
                calendarId=calendar_id,
                body={
                    "summary": "Vachanam connection test",
                    "start": {"dateTime": start.isoformat()},
                    "end": {"dateTime": (start + timedelta(minutes=1)).isoformat()},
                },
            )
            .execute()
        )
        svc._service.events().delete(calendarId=calendar_id, eventId=ev["id"]).execute()
        return True

    return await _asyncio.to_thread(_probe)


@router.get(
    "/{branch_id}/staff",
    response_model=list[StaffMember],
    dependencies=[Depends(queue_today_limit)],
)
async def list_staff(
    branch_id: str,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[StaffMember]:
    """All users with access to this branch (org_admin only — emails are PII)."""
    await assert_branch_access(current_user, branch_id, db)
    _require_org_admin(current_user)

    from backend.models.schema import User

    result = await db.execute(select(User).where(User.branch_ids.contains([branch_id])))
    return [
        StaffMember(user_id=str(u.id), email=u.email, name=u.name, role=u.role)
        for u in result.scalars().all()
    ]


@router.post(
    "/{branch_id}/staff",
    response_model=StaffMember,
    status_code=201,
    dependencies=[Depends(queue_today_limit)],
)
@audit("branch.staff_added", resource_type="user")
async def add_staff(
    branch_id: str,
    body: StaffCreate,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StaffMember:
    """Owner adds a receptionist or doctor login for this branch.
    The new user signs in with email+password (or Google once they sign in
    with the same email)."""
    await assert_branch_access(current_user, branch_id, db)
    _require_org_admin(current_user)
    if body.role not in ("receptionist", "doctor"):
        raise HTTPException(status_code=422, detail="Role must be receptionist or doctor")
    # G6: same strength rules as owner signup — a weak staff/doctor login is a
    # foothold into clinic PII. (Was a bare len>=8 check.)
    from backend.services.validators import validate_password

    try:
        validate_password(body.password)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    from backend.models.schema import Doctor, User
    from backend.routers.auth import _hash_password

    email = body.email.strip().lower()
    existing = (
        await db.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="A user with this email already exists")

    # G5: a doctor-role login must bind to a Doctor row, else /my-schedule (which
    # filters by Doctor.user_id) shows nothing — an orphaned account. Resolve the
    # target doctor from body.doctor_id, else auto-match by the invited_email the
    # owner set when creating the doctor. Fail loudly rather than orphan it.
    target_doctor: Doctor | None = None
    if body.role == "doctor":
        if body.doctor_id:
            try:
                did_uuid = uuid.UUID(body.doctor_id)
            except ValueError:
                raise HTTPException(status_code=422, detail="Invalid doctor_id")
            target_doctor = (
                await db.execute(
                    select(Doctor).where(
                        Doctor.id == did_uuid,
                        Doctor.branch_id == uuid.UUID(branch_id),  # Rule 1
                    )
                )
            ).scalar_one_or_none()
        else:
            target_doctor = (
                await db.execute(
                    select(Doctor).where(
                        Doctor.branch_id == uuid.UUID(branch_id),
                        Doctor.invited_email == email,
                        Doctor.user_id.is_(None),
                    )
                )
            ).scalars().first()
        if target_doctor is None:
            raise HTTPException(
                status_code=422,
                detail="No matching doctor in this branch to link. Create the "
                "doctor first (with this email as invited_email) or pass doctor_id.",
            )
        if target_doctor.user_id is not None:
            raise HTTPException(
                status_code=409, detail="That doctor already has a login."
            )

    user = User(
        org_id=uuid.UUID(current_user.org_id) if current_user.org_id else None,
        email=email,
        name=body.name.strip(),
        role=body.role,
        branch_ids=[branch_id],
        password_hash=_hash_password(body.password),
    )
    db.add(user)
    await db.flush()
    if target_doctor is not None:
        target_doctor.user_id = user.id  # bind the login to the Doctor record
    await db.commit()
    await db.refresh(user)

    request.state.audit_resource_id = str(user.id)
    request.state.audit_user_id = current_user.user_id
    request.state.audit_branch_id = branch_id
    logger.info("staff_added", branch_id=branch_id, role=body.role)

    return StaffMember(user_id=str(user.id), email=user.email, name=user.name, role=user.role)

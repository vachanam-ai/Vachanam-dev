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
    tts_voice: str
    did_number: str | None
    emergency_contact: str | None
    allowed_voices: list[str]


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
    return BranchSettings(
        branch_id=branch_id,
        name=branch.name,
        tts_voice=getattr(branch, "tts_voice", "rupali"),
        did_number=branch.did_number,
        emergency_contact=branch.emergency_contact,
        allowed_voices=ALLOWED_VOICES,
    )


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
    return BranchSettings(
        branch_id=branch_id,
        name=branch.name,
        tts_voice=branch.tts_voice,
        did_number=branch.did_number,
        emergency_contact=branch.emergency_contact,
        allowed_voices=ALLOWED_VOICES,
    )

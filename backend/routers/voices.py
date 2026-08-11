"""Clinic-owned Soniox voice cloning and activation.

Provider credentials and provider-wide inventory never cross this boundary.
Every read/write is branch-scoped and owner-only for mutations.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.database import get_db
from backend.middleware.auth_middleware import CurrentUser, get_current_user
from backend.middleware.branch_guard import assert_branch_access
from backend.middleware.rate_limit import queue_today_limit
from backend.models.schema import Branch, BranchVoice
from backend.services import soniox_voice
from backend.services.audit_service import audit

logger = structlog.get_logger()
router = APIRouter()

_ALLOWED_AUDIO_TYPES = {
    "audio/wav", "audio/x-wav", "audio/mpeg", "audio/mp3", "audio/webm",
    "audio/ogg", "audio/mp4", "audio/x-m4a", "video/webm",
}
_PREVIEW_TEXT = {
    "te": "నమస్కారం. నేను మీ క్లినిక్ వర్చువల్ రిసెప్షనిస్ట్‌ని. మీకు ఎలా సహాయం చేయగలను?",
    "hi": "नमस्ते। मैं आपके क्लिनिक की वर्चुअल रिसेप्शनिस्ट हूँ। मैं आपकी कैसे मदद कर सकती हूँ?",
    "ta": "வணக்கம். நான் உங்கள் கிளினிக்கின் மெய்நிகர் வரவேற்பாளர். உங்களுக்கு எப்படி உதவலாம்?",
    "kn": "ನಮಸ್ಕಾರ. ನಾನು ನಿಮ್ಮ ಕ್ಲಿನಿಕ್‌ನ ವರ್ಚುವಲ್ ರಿಸೆಪ್ಷನಿಸ್ಟ್. ನಿಮಗೆ ಹೇಗೆ ಸಹಾಯ ಮಾಡಲಿ?",
    "ml": "നമസ്കാരം. ഞാൻ നിങ്ങളുടെ ക്ലിനിക്കിന്റെ വെർച്വൽ റിസപ്ഷനിസ്റ്റാണ്. എങ്ങനെ സഹായിക്കാം?",
}


def _owner_only(user: CurrentUser) -> None:
    if user.role != "org_admin":
        raise HTTPException(status_code=403, detail="Only the clinic owner can manage voices")


def _safe_name(value: str) -> str:
    name = " ".join((value or "").strip().split())
    if not 1 <= len(name) <= 80:
        raise HTTPException(status_code=422, detail="Voice name must be 1 to 80 characters")
    if not re.fullmatch(r"[\w .'-]+", name, flags=re.UNICODE):
        raise HTTPException(status_code=422, detail="Voice name contains unsupported characters")
    return name


def _payload(row: BranchVoice, active_voice: str | None) -> dict:
    return {
        "id": str(row.id),
        "voice_id": row.provider_voice_id,
        "name": row.name,
        "filename": row.filename,
        "model": row.model,
        "status": row.status,
        "error_type": row.error_type,
        "error_message": row.error_message,
        "active": bool(row.provider_voice_id and row.provider_voice_id == active_voice),
        "created_at": row.created_at,
    }


async def _branch_and_rows(db: AsyncSession, branch_id: uuid.UUID):
    branch = (await db.execute(select(Branch).where(Branch.id == branch_id))).scalar_one_or_none()
    if branch is None:
        raise HTTPException(status_code=404, detail="Branch not found")
    rows = (
        await db.execute(
            select(BranchVoice)
            .where(BranchVoice.branch_id == branch_id)
            .order_by(BranchVoice.created_at.desc())
        )
    ).scalars().all()
    return branch, rows


async def _sync_rows(db: AsyncSession, rows: list[BranchVoice]) -> str | None:
    if not rows:
        return None
    try:
        provider = await soniox_voice.list_provider_voices()
    except soniox_voice.SonioxVoiceError as exc:
        logger.warning("soniox_voice_sync_failed", error_type=exc.error_type)
        return "Voice status could not be refreshed"

    by_id = {str(item.get("id")): item for item in provider if item.get("id")}
    by_name = {str(item.get("name")): item for item in provider if item.get("name")}
    stale_before = datetime.now(timezone.utc) - timedelta(minutes=2)
    changed = False
    for row in rows:
        item = by_id.get(row.provider_voice_id or "") or by_name.get(row.provider_name)
        if item:
            row.provider_voice_id = str(item["id"])
            row.status, row.error_type, row.error_message = soniox_voice.model_state(item)
            changed = True
        elif row.status == "uploading" and row.created_at and row.created_at < stale_before:
            row.status = "failed"
            row.error_type = "voice_not_found"
            row.error_message = "The upload did not complete. Please create the voice again."
            changed = True
    if changed:
        await db.commit()
    return None


@router.get("/{branch_id}/voice-clones", dependencies=[Depends(queue_today_limit)])
async def list_voice_clones(
    branch_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await assert_branch_access(current_user, branch_id, db)
    _owner_only(current_user)
    branch, rows = await _branch_and_rows(db, uuid.UUID(branch_id))
    sync_warning = await _sync_rows(db, rows)
    return {
        "voices": [_payload(row, branch.tts_voice) for row in rows],
        "clinic_count": len(rows),
        "sync_warning": sync_warning,
    }


@router.post("/{branch_id}/voice-clones", status_code=201, dependencies=[Depends(queue_today_limit)])
@audit("branch.voice_clone_created", resource_type="branch_voice")
async def create_voice_clone(
    branch_id: str,
    request: Request,
    name: str = Form(...),
    consent_confirmed: bool = Form(...),
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await assert_branch_access(current_user, branch_id, db)
    _owner_only(current_user)
    display_name = _safe_name(name)
    if not consent_confirmed:
        raise HTTPException(status_code=422, detail="Voice-owner consent is required")
    content_type = (file.content_type or "").lower()
    if content_type not in _ALLOWED_AUDIO_TYPES:
        raise HTTPException(status_code=415, detail="Upload WAV, MP3, M4A, OGG, or WebM audio")
    audio = await file.read(soniox_voice.MAX_CLIP_BYTES + 1)
    await file.close()
    if not audio:
        raise HTTPException(status_code=422, detail="The audio file is empty")
    if len(audio) > soniox_voice.MAX_CLIP_BYTES:
        raise HTTPException(status_code=413, detail="Reference audio must be 10 MB or smaller")

    branch_uuid = uuid.UUID(branch_id)
    # Lock the owning branch before checking the quota. Locking only clone rows
    # would allow two first uploads to race when a clinic has no rows yet.
    branch = (
        await db.execute(
            select(Branch).where(Branch.id == branch_uuid).with_for_update()
        )
    ).scalar_one_or_none()
    if branch is None:
        raise HTTPException(status_code=404, detail="Branch not found")
    existing_voice = (
        await db.execute(
            select(BranchVoice.id).where(BranchVoice.branch_id == branch_uuid)
        )
    ).scalar_one_or_none()
    if existing_voice is not None:
        raise HTTPException(
            status_code=409,
            detail="This clinic already has a custom voice. Delete it before creating a replacement.",
        )
    duplicate = (
        await db.execute(
            select(BranchVoice.id).where(
                BranchVoice.branch_id == branch_uuid,
                func.lower(BranchVoice.name) == display_name.lower(),
            )
        )
    ).scalar_one_or_none()
    if duplicate:
        raise HTTPException(status_code=409, detail="A voice with this name already exists")

    local_id = uuid.uuid4()
    row = BranchVoice(
        id=local_id,
        branch_id=branch_uuid,
        provider_name=f"vachanam-{branch_uuid.hex[:12]}-{local_id.hex}",
        name=display_name,
        filename=Path(file.filename or "voice-sample.webm").name[:255],
        model=settings.soniox_tts_model,
        status="uploading",
        consent_user_id=uuid.UUID(current_user.user_id),
        consent_text=soniox_voice.CONSENT_TEXT,
    )
    db.add(row)
    await db.commit()

    try:
        provider = await soniox_voice.create_provider_voice(
            provider_name=row.provider_name,
            filename=row.filename,
            content_type=content_type,
            audio=audio,
        )
    except soniox_voice.SonioxVoiceError as exc:
        # A response can be lost after Soniox accepted the upload. Recover by
        # deterministic provider_name before treating the saga as failed.
        provider = None
        if exc.error_type in {"voice_name_conflict", "provider_unavailable"}:
            try:
                provider = next(
                    (item for item in await soniox_voice.list_provider_voices() if item.get("name") == row.provider_name),
                    None,
                )
            except soniox_voice.SonioxVoiceError:
                provider = None
        if provider is None:
            row.status = "failed"
            row.error_type = exc.error_type
            row.error_message = exc.message
            await db.commit()
            raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    provider_voice_id = provider.get("id") or provider.get("voice_id")
    if not provider_voice_id:
        row.status = "failed"
        row.error_type = "provider_invalid_response"
        row.error_message = "Soniox accepted the request but did not return a voice ID."
        await db.commit()
        raise HTTPException(status_code=502, detail=row.error_message)
    row.provider_voice_id = str(provider_voice_id)
    row.status, row.error_type, row.error_message = soniox_voice.model_state(provider)
    await db.commit()
    request.state.audit_resource_id = str(row.id)
    request.state.audit_user_id = current_user.user_id
    request.state.audit_branch_id = branch_id
    logger.info("soniox_voice_clone_created", branch_id=branch_id, clone_id=str(row.id), status=row.status)
    return _payload(row, branch.tts_voice)


@router.post("/{branch_id}/voice-clones/{clone_id}/activate", dependencies=[Depends(queue_today_limit)])
@audit("branch.voice_clone_activated", resource_type="branch_voice")
async def activate_voice_clone(
    branch_id: str,
    clone_id: uuid.UUID,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await assert_branch_access(current_user, branch_id, db)
    _owner_only(current_user)
    row = (
        await db.execute(
            select(BranchVoice)
            .where(BranchVoice.id == clone_id, BranchVoice.branch_id == uuid.UUID(branch_id))
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Voice not found")
    if row.status != "ready" or not row.provider_voice_id:
        raise HTTPException(status_code=409, detail="Voice is not ready yet")
    branch = (
        await db.execute(select(Branch).where(Branch.id == uuid.UUID(branch_id)).with_for_update())
    ).scalar_one()
    branch.tts_voice = row.provider_voice_id
    await db.commit()
    request.state.audit_resource_id = str(row.id)
    request.state.audit_user_id = current_user.user_id
    request.state.audit_branch_id = branch_id
    return {"active": True, "tts_voice": row.provider_voice_id}


@router.post("/{branch_id}/voice-clones/{clone_id}/preview", dependencies=[Depends(queue_today_limit)])
async def preview_voice_clone(
    branch_id: str,
    clone_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await assert_branch_access(current_user, branch_id, db)
    _owner_only(current_user)
    row = (
        await db.execute(
            select(BranchVoice).where(
                BranchVoice.id == clone_id, BranchVoice.branch_id == uuid.UUID(branch_id)
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Voice not found")
    if row.status != "ready" or not row.provider_voice_id:
        raise HTTPException(status_code=409, detail="Voice is not ready yet")
    branch = (await db.execute(select(Branch).where(Branch.id == uuid.UUID(branch_id)))).scalar_one()
    try:
        audio, content_type = await soniox_voice.preview_voice(
            provider_voice_id=row.provider_voice_id,
            language=branch.language or "te",
            text=_PREVIEW_TEXT.get(branch.language or "te", "Hello. I am your clinic's virtual receptionist. How may I help you?"),
        )
    except soniox_voice.SonioxVoiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return Response(audio, media_type=content_type, headers={"Cache-Control": "private, no-store"})


@router.delete("/{branch_id}/voice-clones/{clone_id}", dependencies=[Depends(queue_today_limit)])
@audit("branch.voice_clone_deleted", resource_type="branch_voice")
async def delete_voice_clone(
    branch_id: str,
    clone_id: uuid.UUID,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await assert_branch_access(current_user, branch_id, db)
    _owner_only(current_user)
    row = (
        await db.execute(
            select(BranchVoice)
            .where(BranchVoice.id == clone_id, BranchVoice.branch_id == uuid.UUID(branch_id))
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        return {"deleted": True}
    branch = (
        await db.execute(select(Branch).where(Branch.id == uuid.UUID(branch_id)).with_for_update())
    ).scalar_one()
    prior_status = row.status
    if row.provider_voice_id and branch.tts_voice == row.provider_voice_id:
        branch.tts_voice = settings.soniox_tts_default_voice
    row.status = "deleting"
    await db.commit()
    if row.provider_voice_id:
        try:
            await soniox_voice.delete_provider_voice(row.provider_voice_id)
        except soniox_voice.SonioxVoiceError as exc:
            row.status = prior_status
            await db.commit()
            raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    await db.delete(row)
    await db.commit()
    request.state.audit_resource_id = str(clone_id)
    request.state.audit_user_id = current_user.user_id
    request.state.audit_branch_id = branch_id
    return {"deleted": True, "active_voice": branch.tts_voice}

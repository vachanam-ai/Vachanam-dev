"""Branch settings endpoints (clinic-facing).

Rule 1: every query filters by branch_id; access enforced via assert_branch_access.
Currently: voice selection for the clinic's AI agent.
"""
import uuid

import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
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

# TTS voices come from the smallest.ai catalog (GET /branches/{id}/voices) +
# any cloned voice — no static list. A clinic's chosen voice_id lives in
# branches.tts_voice (NULL → the language's default smallest voice).

# Voice-agent languages a clinic can pick (single source of truth: agent.i18n).
from agent.i18n import LANGUAGES as _LANGUAGES  # noqa: E402

ALLOWED_LANGUAGES = list(_LANGUAGES.keys())
# For the Settings dropdown: code + English name + endonym.
LANGUAGE_OPTIONS = [
    {"code": c, "name": cfg.name, "native_name": cfg.native_name}
    for c, cfg in _LANGUAGES.items()
]


class BranchSettings(BaseModel):
    branch_id: str
    name: str
    address: str | None = None
    city: str | None = None
    clinic_phone: str | None = None
    tts_voice: str | None = None   # smallest.ai voice_id; NULL → language default
    language: str = "te"
    did_number: str | None
    emergency_contact: str | None
    google_calendar_id: str | None = None
    allowed_languages: list[dict] = []
    doctors_count: int = 0
    staff_count: int = 0
    did_wired: bool | None = None  # set on PATCH when DID trunk sync runs
    voice_cloning_allowed: bool = True  # included on every plan (UI hint)


# Voice cloning is included on EVERY plan (Vinay 2026-06-20) — no plan gate.


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
        tts_voice=getattr(branch, "tts_voice", None),
        language=getattr(branch, "language", "te") or "te",
        did_number=branch.did_number,
        emergency_contact=branch.emergency_contact,
        google_calendar_id=branch.google_calendar_id,
        allowed_languages=LANGUAGE_OPTIONS,
        doctors_count=doctors_count,
        staff_count=staff_count,
        did_wired=did_wired,
        voice_cloning_allowed=True,
    )


import re as _re

# A smallest.ai voice_id (catalog like "padmaja" or a cloned "voice_..."): letters,
# digits, _ and -, 1-64 chars. The picker only offers catalog/cloned ids; this is
# just a sanity guard (the full catalog is dynamic, so we don't whitelist names).
_VOICE_ID_RE = _re.compile(r"^[A-Za-z0-9_-]{1,64}$")


# Standard Indian-clinic FAQ template (web-researched 2026-07-03: consultation
# fee, timings/Sunday, payment modes, free-followup window, location/parking,
# insurance, reports, what to bring, home visits, services). Clinics fill the
# answers in Settings; unanswered rows are skipped at prompt time.
FAQ_TEMPLATE: list[dict] = [
    {"q": "What are the clinic timings? Are you open on Sundays?", "a": ""},
    {"q": "What is the consultation fee?", "a": ""},
    {"q": "Is a follow-up visit free? Within how many days?", "a": ""},
    {"q": "Where exactly is the clinic located? Any landmark?", "a": ""},
    {"q": "Is parking available?", "a": ""},
    {"q": "What payment methods do you accept (cash / UPI / card)?", "a": ""},
    {"q": "Do you accept health insurance?", "a": ""},
    {"q": "When will test reports be ready? Can I get them on WhatsApp?", "a": ""},
    {"q": "What should I bring for the first visit (old reports, ID)?", "a": ""},
    {"q": "Do you do home visits?", "a": ""},
    {"q": "What treatments/services does the clinic offer?", "a": ""},
]

_FAQ_MAX_ITEMS = 30
_FAQ_Q_MAX = 200
_FAQ_A_MAX = 500


class FaqItem(BaseModel):
    q: str
    a: str = ""


class FaqUpdate(BaseModel):
    faq: list[FaqItem]


class VoiceUpdate(BaseModel):
    tts_voice: str | None = None   # smallest voice_id (omit to change language only)
    language: str | None = None    # optional: also set the clinic's spoken language


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
    if body.tts_voice is not None and not _VOICE_ID_RE.match(body.tts_voice):
        raise HTTPException(status_code=422, detail="Invalid voice id")
    if body.language is not None and body.language not in ALLOWED_LANGUAGES:
        raise HTTPException(status_code=422, detail=f"Language must be one of {ALLOWED_LANGUAGES}")
    if body.tts_voice is None and body.language is None:
        raise HTTPException(status_code=422, detail="Provide a voice or a language")

    result = await db.execute(select(Branch).where(Branch.id == uuid.UUID(branch_id)))
    branch = result.scalar_one_or_none()
    if branch is None:
        raise HTTPException(status_code=404, detail="Branch not found")

    if body.tts_voice is not None:
        branch.tts_voice = body.tts_voice
    if body.language is not None:
        branch.language = body.language
    await db.commit()

    request.state.audit_resource_id = branch_id
    request.state.audit_user_id = current_user.user_id
    request.state.audit_branch_id = branch_id

    logger.info(
        "branch_voice_changed", branch_id=branch_id, voice=body.tts_voice, language=body.language
    )
    return await _settings_payload(db, branch, branch_id)


# ── smallest.ai voice catalog + voice cloning ───────────────────────────────

# Voice-clone sample: a 5-15s clip. Cap the upload so a huge file can't OOM the
# worker (RULE: bound untrusted input).
_MAX_CLONE_BYTES = 10 * 1024 * 1024  # 10 MB


@router.get("/{branch_id}/voices", dependencies=[Depends(queue_today_limit)])
async def list_branch_voices(
    branch_id: str,
    request: Request,
    language: str | None = None,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """smallest.ai voice catalog for the Settings picker, filtered to the clinic's
    language (or an explicit ?language=). Includes which voice is current."""
    await assert_branch_access(current_user, branch_id, db)
    branch = (
        await db.execute(select(Branch).where(Branch.id == uuid.UUID(branch_id)))
    ).scalar_one_or_none()
    if branch is None:
        raise HTTPException(status_code=404, detail="Branch not found")
    lang = (language or getattr(branch, "language", None) or "te").lower()

    from backend.services import smallest_voice

    try:
        catalog = smallest_voice.list_voices(lang)
    except smallest_voice.VoiceServiceError as e:
        raise HTTPException(status_code=502, detail=str(e))

    # Prepend ALL of this clinic's registered cloned voices (tenant-scoped) so
    # they're selectable in the picker, tagged cloned=true. No language filter:
    # a clinic clones a handful of its OWN voices and may use a voice cloned
    # from a Tamil sample on its Telugu agent — hiding it by language made the
    # active voice invisible in the picker (prod 2026-07-03).
    cloned = [
        {
            "voice_id": cv.get("voice_id"),
            "display_name": cv.get("name") or cv.get("voice_id"),
            "gender": None,
            "languages": [(cv.get("language") or lang).lower()],
            "cloned": True,
        }
        for cv in (getattr(branch, "cloned_voices", None) or [])
        if cv.get("voice_id")
    ]
    return {
        "language": lang,
        "current": getattr(branch, "tts_voice", None),
        "voices": cloned + catalog,
    }


@router.get("/{branch_id}/faq")
async def get_faq(
    branch_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """The clinic's FAQ (agent answers these on calls) + the fill-in template
    + recent caller questions the FAQ could NOT answer (grow the FAQ from
    real calls)."""
    await assert_branch_access(current_user, branch_id, db)
    branch = (
        await db.execute(select(Branch).where(Branch.id == uuid.UUID(branch_id)))
    ).scalar_one_or_none()
    if branch is None:
        raise HTTPException(status_code=404, detail="Branch not found")
    from backend.models.schema import ClinicQuestion

    asked = (
        await db.execute(
            select(ClinicQuestion)
            .where(ClinicQuestion.branch_id == uuid.UUID(branch_id))
            .order_by(ClinicQuestion.created_at.desc())
            .limit(30)
        )
    ).scalars().all()
    return {
        "faq": getattr(branch, "faq", None) or [],
        "template": FAQ_TEMPLATE,
        "asked": [
            {"question": a.question, "at": a.created_at.isoformat() if a.created_at else None}
            for a in asked
        ],
    }


@router.put("/{branch_id}/faq")
async def save_faq(
    branch_id: str,
    body: FaqUpdate,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Save the clinic FAQ (org_admin). The agent speaks these answers, so cap
    sizes (RULE 6: they reach TTS via the LLM) and strip whitespace."""
    await assert_branch_access(current_user, branch_id, db)
    if current_user.role != "org_admin":
        raise HTTPException(status_code=403, detail="Only the clinic owner can edit the FAQ")
    if len(body.faq) > _FAQ_MAX_ITEMS:
        raise HTTPException(status_code=422, detail=f"At most {_FAQ_MAX_ITEMS} FAQ entries")
    cleaned = []
    for item in body.faq:
        q = item.q.strip()
        a = item.a.strip()
        if not q:
            continue  # empty question row from the editor — drop silently
        if len(q) > _FAQ_Q_MAX or len(a) > _FAQ_A_MAX:
            raise HTTPException(
                status_code=422,
                detail=f"Question ≤{_FAQ_Q_MAX} chars, answer ≤{_FAQ_A_MAX} chars",
            )
        cleaned.append({"q": q, "a": a})
    branch = (
        await db.execute(select(Branch).where(Branch.id == uuid.UUID(branch_id)))
    ).scalar_one_or_none()
    if branch is None:
        raise HTTPException(status_code=404, detail="Branch not found")
    branch.faq = cleaned  # reassign — JSONB change tracking
    await db.commit()
    logger.info("branch_faq_saved", branch_id=branch_id, items=len(cleaned))
    return {"faq": cleaned, "template": FAQ_TEMPLATE}


class ClonedVoiceRegister(BaseModel):
    voice_id: str          # the smallest "voice_..." id from the dashboard clone
    name: str              # label shown in the picker (e.g. "Dr Vinay")
    language: str          # which language it speaks (te/hi/...)
    set_current: bool = True  # also make it the agent's voice now


@router.post(
    "/{branch_id}/cloned-voices",
    response_model=BranchSettings,
    dependencies=[Depends(queue_today_limit)],
)
@audit("branch.cloned_voice_registered", resource_type="branch")
async def register_cloned_voice(
    branch_id: str,
    body: ClonedVoiceRegister,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BranchSettings:
    """Register a smallest.ai cloned voice (created in the dashboard) so it shows
    in the picker for its language and can be the agent's voice. org_admin only."""
    await assert_branch_access(current_user, branch_id, db)
    if current_user.role != "org_admin":
        raise HTTPException(status_code=403, detail="Only the clinic owner can add a voice")
    if not _VOICE_ID_RE.match(body.voice_id or ""):
        raise HTTPException(status_code=422, detail="Invalid voice id")
    if not body.name.strip():
        raise HTTPException(status_code=422, detail="A voice name is required")
    if body.language not in ALLOWED_LANGUAGES:
        raise HTTPException(status_code=422, detail=f"Language must be one of {ALLOWED_LANGUAGES}")

    branch = (
        await db.execute(select(Branch).where(Branch.id == uuid.UUID(branch_id)))
    ).scalar_one_or_none()
    if branch is None:
        raise HTTPException(status_code=404, detail="Branch not found")

    lst = [c for c in (branch.cloned_voices or []) if c.get("voice_id") != body.voice_id]
    lst.append({"voice_id": body.voice_id, "name": body.name.strip(), "language": body.language})
    branch.cloned_voices = lst  # reassign so SQLAlchemy detects the JSONB change
    if body.set_current:
        branch.tts_voice = body.voice_id
        branch.language = body.language
    await db.commit()

    request.state.audit_resource_id = branch_id
    request.state.audit_user_id = current_user.user_id
    request.state.audit_branch_id = branch_id
    logger.info("cloned_voice_registered", branch_id=branch_id, voice_id=body.voice_id, language=body.language)
    return await _settings_payload(db, branch, branch_id)


@router.delete(
    "/{branch_id}/cloned-voices/{voice_id}",
    response_model=BranchSettings,
    dependencies=[Depends(queue_today_limit)],
)
@audit("branch.cloned_voice_removed", resource_type="branch")
async def unregister_cloned_voice(
    branch_id: str,
    voice_id: str,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BranchSettings:
    """Remove a registered cloned voice. If it was the agent's voice, fall back to
    the language default. org_admin only."""
    await assert_branch_access(current_user, branch_id, db)
    if current_user.role != "org_admin":
        raise HTTPException(status_code=403, detail="Only the clinic owner can remove a voice")
    branch = (
        await db.execute(select(Branch).where(Branch.id == uuid.UUID(branch_id)))
    ).scalar_one_or_none()
    if branch is None:
        raise HTTPException(status_code=404, detail="Branch not found")

    branch.cloned_voices = [c for c in (branch.cloned_voices or []) if c.get("voice_id") != voice_id]
    if branch.tts_voice == voice_id:
        branch.tts_voice = None  # → agent uses the language default
    await db.commit()

    request.state.audit_resource_id = branch_id
    request.state.audit_user_id = current_user.user_id
    request.state.audit_branch_id = branch_id
    logger.info("cloned_voice_removed", branch_id=branch_id, voice_id=voice_id)
    return await _settings_payload(db, branch, branch_id)


@router.post(
    "/{branch_id}/voice-clone",
    response_model=BranchSettings,
    dependencies=[Depends(queue_today_limit)],
)
@audit("branch.voice_cloned", resource_type="branch")
async def clone_branch_voice(
    branch_id: str,
    request: Request,
    display_name: str = Form(...),
    file: UploadFile = File(...),
    language: str | None = Form(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BranchSettings:
    """Clone a voice from an uploaded sample and set it as the clinic's voice.
    org_admin only. The cloned voice_id is stored on this branch (tenant-scoped)."""
    await assert_branch_access(current_user, branch_id, db)
    if current_user.role != "org_admin":
        raise HTTPException(status_code=403, detail="Only the clinic owner can clone a voice")
    if not display_name.strip():
        raise HTTPException(status_code=422, detail="A voice name is required")

    audio = await file.read()
    if not audio:
        raise HTTPException(status_code=422, detail="Empty audio file")
    if len(audio) > _MAX_CLONE_BYTES:
        raise HTTPException(status_code=413, detail="Audio sample too large (max 10 MB)")

    branch = (
        await db.execute(select(Branch).where(Branch.id == uuid.UUID(branch_id)))
    ).scalar_one_or_none()
    if branch is None:
        raise HTTPException(status_code=404, detail="Branch not found")

    from backend.services import smallest_voice

    # Clone in the chosen language (form field), defaulting to the clinic's
    # spoken language. smallest's cloning API takes the ISO code — it 400s on
    # full names now ("Invalid language. Supported: en, hi, ... te, pa, or",
    # prod 2026-07-03; it previously accepted "telugu").
    if language is not None and language not in ALLOWED_LANGUAGES:
        raise HTTPException(
            status_code=422, detail=f"Language must be one of {ALLOWED_LANGUAGES}"
        )
    clone_language = language or (getattr(branch, "language", None) or "te")
    try:
        _tag_cfg = _LANGUAGES.get(clone_language)
        voice_id = smallest_voice.clone_voice(
            display_name.strip(), file.filename or "sample.wav", audio,
            language=clone_language,
            tag=(_tag_cfg.name if _tag_cfg else None),  # "Tamil" chip in their dashboard
        )
    except smallest_voice.VoiceServiceError as e:
        raise HTTPException(status_code=502, detail=str(e))

    branch.tts_voice = voice_id
    # Register the clone so it has a NAME in the picker + a Remove row — without
    # this the voice spoke but "sreelekha" appeared nowhere (prod 2026-07-03).
    # Reassign (not mutate) so SQLAlchemy detects the JSONB change.
    branch.cloned_voices = [
        c for c in (branch.cloned_voices or []) if c.get("voice_id") != voice_id
    ] + [{"voice_id": voice_id, "name": display_name.strip(), "language": clone_language}]
    await db.commit()

    request.state.audit_resource_id = branch_id
    request.state.audit_user_id = current_user.user_id
    request.state.audit_branch_id = branch_id
    logger.info("branch_voice_cloned", branch_id=branch_id, voice_id=voice_id)
    return await _settings_payload(db, branch, branch_id)


@router.delete(
    "/{branch_id}/voice-clone",
    response_model=BranchSettings,
    dependencies=[Depends(queue_today_limit)],
)
@audit("branch.voice_clone_deleted", resource_type="branch")
async def delete_branch_voice_clone(
    branch_id: str,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BranchSettings:
    """Remove the clinic's cloned voice (delete it at smallest.ai best-effort and
    clear it locally so the agent falls back to the language default). org_admin only."""
    await assert_branch_access(current_user, branch_id, db)
    if current_user.role != "org_admin":
        raise HTTPException(status_code=403, detail="Only the clinic owner can remove the voice")
    branch = (
        await db.execute(select(Branch).where(Branch.id == uuid.UUID(branch_id)))
    ).scalar_one_or_none()
    if branch is None:
        raise HTTPException(status_code=404, detail="Branch not found")

    current = getattr(branch, "tts_voice", None)
    if current:
        from backend.services import smallest_voice

        smallest_voice.delete_cloned_voice(current)  # best-effort, never raises out
    branch.tts_voice = None  # → agent uses the language's default voice
    await db.commit()

    request.state.audit_resource_id = branch_id
    request.state.audit_user_id = current_user.user_id
    request.state.audit_branch_id = branch_id
    logger.info("branch_voice_clone_deleted", branch_id=branch_id)
    return await _settings_payload(db, branch, branch_id)


# ── Per-clinic Vobiz sub-account (concurrency isolation) ────────────────────


class TelephonyUpdate(BaseModel):
    vobiz_subaccount_id: str | None = None
    vobiz_sip_username: str | None = None
    vobiz_sip_password: str | None = None  # plaintext IN; stored encrypted at rest
    vobiz_sip_domain: str | None = None
    outbound_trunk_id: str | None = None


class TelephonySettings(BaseModel):
    """Non-secret view of a branch's telephony config. The SIP password is NEVER
    returned — only whether one is set."""
    vobiz_subaccount_id: str | None = None
    vobiz_sip_username: str | None = None
    vobiz_sip_domain: str | None = None
    outbound_trunk_id: str | None = None
    has_sip_password: bool = False


def _telephony_payload(branch: Branch) -> TelephonySettings:
    return TelephonySettings(
        vobiz_subaccount_id=getattr(branch, "vobiz_subaccount_id", None),
        vobiz_sip_username=getattr(branch, "vobiz_sip_username", None),
        vobiz_sip_domain=getattr(branch, "vobiz_sip_domain", None),
        outbound_trunk_id=getattr(branch, "outbound_trunk_id", None),
        has_sip_password=bool(getattr(branch, "vobiz_sip_password_enc", None)),
    )


@router.get(
    "/{branch_id}/telephony",
    response_model=TelephonySettings,
    dependencies=[Depends(queue_today_limit)],
)
async def get_branch_telephony(
    branch_id: str,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TelephonySettings:
    """The branch's Vobiz sub-account config (no secret). org_admin only."""
    await assert_branch_access(current_user, branch_id, db)
    if current_user.role != "org_admin":
        raise HTTPException(status_code=403, detail="Only the clinic owner can view telephony settings")
    branch = (
        await db.execute(select(Branch).where(Branch.id == uuid.UUID(branch_id)))
    ).scalar_one_or_none()
    if branch is None:
        raise HTTPException(status_code=404, detail="Branch not found")
    return _telephony_payload(branch)


@router.patch(
    "/{branch_id}/telephony",
    response_model=TelephonySettings,
    dependencies=[Depends(queue_today_limit)],
)
@audit("branch.telephony_changed", resource_type="branch")
async def update_branch_telephony(
    branch_id: str,
    body: TelephonyUpdate,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TelephonySettings:
    """Set a clinic's Vobiz sub-account credentials for concurrency isolation.
    The SIP password is encrypted at rest (DPDP/RULE 9) — never stored plaintext.
    org_admin only. Only provided fields are updated; omit a field to leave it."""
    from backend.services.crypto import encrypt_secret

    await assert_branch_access(current_user, branch_id, db)
    if current_user.role != "org_admin":
        raise HTTPException(status_code=403, detail="Only the clinic owner can change telephony settings")

    branch = (
        await db.execute(select(Branch).where(Branch.id == uuid.UUID(branch_id)))
    ).scalar_one_or_none()
    if branch is None:
        raise HTTPException(status_code=404, detail="Branch not found")

    for field in ("vobiz_subaccount_id", "vobiz_sip_username", "vobiz_sip_domain", "outbound_trunk_id"):
        val = getattr(body, field)
        if val is not None:
            setattr(branch, field, val.strip() or None)
    if body.vobiz_sip_password is not None:
        # Empty string clears the stored secret; otherwise store the ciphertext.
        branch.vobiz_sip_password_enc = (
            encrypt_secret(body.vobiz_sip_password) if body.vobiz_sip_password else None
        )
    await db.commit()

    request.state.audit_resource_id = branch_id
    request.state.audit_user_id = current_user.user_id
    request.state.audit_branch_id = branch_id

    logger.info(
        "branch_telephony_changed",
        branch_id=branch_id,
        subaccount=bool(branch.vobiz_subaccount_id),
        has_password=bool(branch.vobiz_sip_password_enc),
    )
    return _telephony_payload(branch)


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

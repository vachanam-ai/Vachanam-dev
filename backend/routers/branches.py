"""Branch settings endpoints (clinic-facing).

Rule 1: every query filters by branch_id; access enforced via assert_branch_access.
Currently: voice selection for the clinic's AI agent.
"""
import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.middleware.auth_middleware import CurrentUser, get_current_user
from backend.middleware.branch_guard import assert_branch_access
from backend.middleware.rate_limit import queue_today_limit
from backend.models.schema import Branch
from backend.services.audit_service import audit

logger = structlog.get_logger()
router = APIRouter()

# Soniox is the sole TTS provider. A clinic's chosen catalog voice lives in
# branches.tts_voice; legacy values resolve to the configured Soniox default.
SONIOX_VOICES = (
    {"voice_id": "Priya", "display_name": "Priya", "gender": "female"},
    {"voice_id": "Meera", "display_name": "Meera", "gender": "female"},
    {"voice_id": "Arjun", "display_name": "Arjun", "gender": "male"},
    {"voice_id": "Rohan", "display_name": "Rohan", "gender": "male"},
)
SONIOX_VOICE_IDS = {voice["voice_id"] for voice in SONIOX_VOICES}

# Voice-agent languages a clinic can pick (single source of truth: agent.i18n).
from agent.i18n import LANGUAGES as _LANGUAGES  # noqa: E402

ALLOWED_LANGUAGES = list(_LANGUAGES.keys())
# For the Settings dropdown: code + English name + endonym.
LANGUAGE_OPTIONS = [
    {"code": c, "name": cfg.name, "native_name": cfg.native_name}
    for c, cfg in _LANGUAGES.items()
]


async def _org_plan(db, branch) -> str:
    """The owning org's plan key (repricing 2026-07-11 plan gates)."""
    plan, _ = await _org_plan_and_start(db, branch)
    return plan


async def _org_plan_and_start(db, branch) -> tuple:
    """(plan, subscription_started_at) — the launch-offer gates (#391) need
    the subscription start to know whether the first-3-months window applies."""
    from backend.models.schema import Organization

    org = (
        await db.execute(
            select(Organization).where(Organization.id == branch.org_id)
        )
    ).scalar_one_or_none()
    return (
        (org.plan if org and org.plan else "clinic"),
        getattr(org, "subscription_started_at", None) if org else None,
    )


def _assert_plan_language(plan: str, language: str) -> None:
    """All plans carry all languages since 2026-07-12 (PLAN_LANGUAGES all
    None) — this gate stays as the seam in case a future plan re-restricts."""
    from backend.services.billing_math import PLAN_LANGUAGES, PLANS

    allowed = PLAN_LANGUAGES.get(plan, None)
    if allowed is not None and language not in allowed:
        name = PLANS[plan].display_name if plan in PLANS else plan
        raise HTTPException(
            status_code=403,
            detail=f"The {name} plan includes {', '.join(allowed)}. Upgrade for more languages.",
        )


class BranchSettings(BaseModel):
    branch_id: str
    name: str
    address: str | None = None
    city: str | None = None
    clinic_phone: str | None = None
    tts_voice: str | None = None   # Soniox catalog voice; NULL/legacy → default
    language: str = "te"
    did_number: str | None
    emergency_contact: str | None
    google_calendar_id: str | None = None
    allowed_languages: list[dict] = []
    doctors_count: int = 0
    staff_count: int = 0
    did_wired: bool | None = None  # set on PATCH when DID trunk sync runs
    whatsapp_linked: bool = False  # WA T9: read-only status (linking is concierge)




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
    # Plan-aware UI hints (repricing 2026-07-11): the Settings page only offers
    # what the org's plan includes — languages list filtered.
    from backend.services.billing_math import PLAN_LANGUAGES

    plan, _sub_start = await _org_plan_and_start(db, branch)
    plan_langs = PLAN_LANGUAGES.get(plan, None)
    lang_options = (
        LANGUAGE_OPTIONS if plan_langs is None
        else [o for o in LANGUAGE_OPTIONS if o["code"] in plan_langs]
    )
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
        allowed_languages=lang_options,
        doctors_count=doctors_count,
        staff_count=staff_count,
        did_wired=did_wired,
        whatsapp_linked=bool(getattr(branch, "wa_phone_number_id", None)),
    )


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
# 500 was too tight for real clinic answers (insurance lists, per-day timings)
# and failed the WHOLE save (Vinay 2026-07-17: "unable to save FAQs"). The
# agent's LLM grounds on these and compresses for speech, so 1000 is safe.
_FAQ_A_MAX = 1000


class FaqItem(BaseModel):
    q: str
    a: str = ""


class FaqUpdate(BaseModel):
    faq: list[FaqItem]


class VoiceUpdate(BaseModel):
    tts_voice: str | None = None   # Soniox catalog voice (omit to change language only)
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
    if body.tts_voice is not None and body.tts_voice not in SONIOX_VOICE_IDS:
        raise HTTPException(
            status_code=422,
            detail=f"Voice must be one of {sorted(SONIOX_VOICE_IDS)}",
        )
    if body.language is not None and body.language not in ALLOWED_LANGUAGES:
        raise HTTPException(status_code=422, detail=f"Language must be one of {ALLOWED_LANGUAGES}")
    if body.tts_voice is None and body.language is None:
        raise HTTPException(status_code=422, detail="Provide a voice or a language")

    result = await db.execute(select(Branch).where(Branch.id == uuid.UUID(branch_id)))
    branch = result.scalar_one_or_none()
    if branch is None:
        raise HTTPException(status_code=404, detail="Branch not found")

    if body.language is not None:
        _assert_plan_language(await _org_plan(db, branch), body.language)
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


# ── voice catalog (cloning REMOVED 2026-07-24, Vinay) ───────────────────────



@router.get("/{branch_id}/voices", dependencies=[Depends(queue_today_limit)])
async def list_branch_voices(
    branch_id: str,
    request: Request,
    language: str | None = None,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Soniox voice catalog for the Settings picker."""
    await assert_branch_access(current_user, branch_id, db)
    branch = (
        await db.execute(select(Branch).where(Branch.id == uuid.UUID(branch_id)))
    ).scalar_one_or_none()
    if branch is None:
        raise HTTPException(status_code=404, detail="Branch not found")
    lang = (language or getattr(branch, "language", None) or "te").lower()

    current = getattr(branch, "tts_voice", None)
    if current not in SONIOX_VOICE_IDS:
        from backend.config import settings as _settings
        current = _settings.soniox_tts_default_voice
    return {
        "language": lang,
        "current": current,
        "voices": [{**voice, "languages": [lang]} for voice in SONIOX_VOICES],
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
        # Name the offending row — a bare "too long" left the owner unable to
        # find which of 11+ rows blocked the whole save.
        if len(q) > _FAQ_Q_MAX:
            raise HTTPException(
                status_code=422,
                detail=f'Question "{q[:60]}…" is too long ({len(q)}/{_FAQ_Q_MAX} characters)',
            )
        if len(a) > _FAQ_A_MAX:
            raise HTTPException(
                status_code=422,
                detail=f'Answer for "{q[:60]}" is too long ({len(a)}/{_FAQ_A_MAX} characters)',
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


@router.get("/{branch_id}/messages")
async def list_messages(
    branch_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Caller messages the voice agent took for the doctor/clinic (#349).
    Pending first, urgent first within that, newest first; latest 50."""
    await assert_branch_access(current_user, branch_id, db)
    from backend.models.schema import Patient, PatientMessage

    rows = (
        await db.execute(
            select(PatientMessage, Patient.name)
            .outerjoin(Patient, Patient.id == PatientMessage.patient_id)
            .where(PatientMessage.branch_id == uuid.UUID(branch_id))
            .order_by(
                (PatientMessage.status == "pending").desc(),
                PatientMessage.urgent.desc(),
                PatientMessage.created_at.desc(),
            )
            .limit(50)
        )
    ).all()
    return {
        "messages": [
            {
                "id": str(m.id),
                "message": m.message,
                "urgent": m.urgent,
                "status": m.status,
                "caller_phone": m.caller_phone,
                "patient_name": name,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m, name in rows
        ],
        "pending": sum(1 for m, _ in rows if m.status == "pending"),
    }


@router.get("/{branch_id}/ratings/summary")
async def ratings_summary(
    branch_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """WhatsApp post-visit ratings rollup for the Dashboard (WA T9).
    RULE 1: branch-scoped; scores only — ratings never carry text."""
    await assert_branch_access(current_user, branch_id, db)
    from sqlalchemy import func as safunc

    from backend.models.schema import Rating

    row = (
        await db.execute(
            select(
                safunc.avg(Rating.score),
                safunc.count(Rating.id),
                safunc.count(Rating.id).filter(Rating.score <= 2),
            ).where(Rating.branch_id == uuid.UUID(branch_id))
        )
    ).one()
    avg, count, low = row
    return {
        "avg": round(float(avg), 2) if avg is not None else None,
        "count": int(count or 0),
        "low_count": int(low or 0),
    }


@router.patch("/{branch_id}/messages/{message_id}")
async def resolve_message(
    branch_id: str,
    message_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Mark a caller message done (the clinic called back / handled it)."""
    await assert_branch_access(current_user, branch_id, db)
    from backend.models.schema import PatientMessage

    m = (
        await db.execute(
            select(PatientMessage).where(
                PatientMessage.id == uuid.UUID(message_id),
                # RULE 1: id alone is not enough — the row must belong to the
                # branch the caller is authorized on.
                PatientMessage.branch_id == uuid.UUID(branch_id),
            )
        )
    ).scalar_one_or_none()
    if m is None:
        raise HTTPException(status_code=404, detail="Message not found")
    m.status = "done"
    m.resolved_at = datetime.now(timezone.utc)
    await db.commit()
    logger.info("patient_message_resolved", branch_id=branch_id, message_id=message_id)
    return {"id": str(m.id), "status": m.status}


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
    name: str | None = Field(default=None, max_length=255)
    address: str | None = Field(default=None, max_length=2000)
    city: str | None = Field(default=None, max_length=100)
    clinic_phone: str | None = Field(default=None, max_length=20)
    emergency_contact: str | None = Field(default=None, max_length=20)
    google_calendar_id: str | None = Field(default=None, max_length=255)
    did_number: str | None = Field(default=None, max_length=20)

    @field_validator("clinic_phone", "emergency_contact")
    @classmethod
    def _normalise_contact(cls, value):
        if value is None or not value.strip():
            return value
        from backend.services.validators import normalize_indian_phone
        return normalize_indian_phone(value)


class StaffMember(BaseModel):
    user_id: str
    email: str
    name: str | None
    role: str


class StaffCreate(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    name: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=8, max_length=256)
    role: str = "receptionist"
    doctor_id: str | None = None  # link a doctor-role login to its Doctor row (G5)

    @field_validator("email")
    @classmethod
    def _normalise_email(cls, value):
        from backend.services.validators import normalize_email
        try:
            return normalize_email(value)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc


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

    # SEC #9: a Google Calendar ID, like a DID, must belong to exactly ONE
    # branch. Our shared service account has writer access to every clinic
    # calendar shared with it, so if branch B set branch A's calendar_id, B's
    # bookings (patient name + last-4 + token) would be written into A's
    # calendar — a cross-tenant PII spill. Reject a calendar already claimed by
    # a different branch (mirrors the DID guard above).
    if body.google_calendar_id is not None and body.google_calendar_id.strip():
        cal_id = body.google_calendar_id.strip()
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"calendar:{cal_id}"},
        )
        cal_clash = (
            await db.execute(
                select(Branch).where(
                    Branch.google_calendar_id == cal_id, Branch.id != branch.id
                )
            )
        ).scalar_one_or_none()
        from backend.models.schema import Doctor
        doctor_clash = (
            await db.execute(
                select(Doctor).where(Doctor.google_calendar_id == cal_id)
            )
        ).scalars().first()
        if cal_clash is not None or doctor_clash is not None:
            logger.warning("calendar_id_collision_blocked", branch_id=branch_id)
            raise HTTPException(
                status_code=409,
                detail="This Google Calendar is already linked to another clinic.",
            )

    old_did = branch.did_number  # capture before mutate (G9 trunk cleanup)
    for field in (
        "name", "address", "city", "clinic_phone",
        "emergency_contact", "google_calendar_id", "did_number",
    ):
        value = getattr(body, field)
        if value is not None:
            setattr(branch, field, value.strip() or None)
    # LOOP GUARD (Vinay 2026-07-17): the escalation/emergency number is where
    # we SEND callers when the AI line is blocked or a human handover is
    # needed. The clinic's own number forwards INTO the AI line — pointing the
    # escalation there would loop the caller straight back to the agent.
    if branch.emergency_contact and branch.emergency_contact in (
        branch.clinic_phone, branch.did_number,
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "The escalation number can't be the clinic's own number — that "
                "line forwards back to the AI. Use a number a human answers "
                "(e.g. the owner's mobile)."
            ),
        )
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
    _require_org_admin(current_user)
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


@router.delete(
    "/{branch_id}/staff/{user_id}",
    dependencies=[Depends(queue_today_limit)],
)
@audit("branch.staff_removed", resource_type="user")
async def remove_staff(
    branch_id: str,
    user_id: str,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Owner removes a staff login (DPDP account deletion, Vinay 2026-07-17).
    Doctor rows are unlinked (their schedule/treatments stay — the LOGIN dies,
    not the clinic's records). Owners cannot delete themselves here — the
    delete-clinic flow handles the whole org."""
    await assert_branch_access(current_user, branch_id, db)
    if current_user.role != "org_admin":
        raise HTTPException(status_code=403, detail="Only the clinic owner can remove logins")
    if user_id == current_user.user_id:
        raise HTTPException(
            status_code=422,
            detail="You can't remove your own login — use Delete clinic to close the account",
        )
    from backend.models.schema import Doctor, User

    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid user id")
    target = (
        await db.execute(
            select(User).where(
                User.id == uid,
                User.org_id == uuid.UUID(current_user.org_id),  # RULE 1
            )
        )
    ).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    if target.role == "org_admin":
        raise HTTPException(status_code=422, detail="Another owner login can't be removed here")

    # Unlink any doctor bound to this login; clinical records stay.
    await db.execute(
        Doctor.__table__.update()
        .where(Doctor.user_id == uid)
        .values(user_id=None)
    )
    await db.execute(User.__table__.delete().where(User.id == uid))
    await db.commit()
    request.state.audit_resource_id = user_id
    request.state.audit_user_id = current_user.user_id
    request.state.audit_branch_id = branch_id
    logger.info("staff_removed", branch_id=branch_id, removed=user_id[-4:])
    return {"deleted": True, "user_id": user_id}

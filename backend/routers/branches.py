"""Branch settings endpoints (clinic-facing).

Rule 1: every query filters by branch_id; access enforced via assert_branch_access.
Currently: voice selection for the clinic's AI agent.
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.database import get_db
from backend.middleware.auth_middleware import (
    CurrentUser,
    get_current_user,
    revoke_user_version,
)
from backend.middleware.branch_guard import assert_branch_access
from backend.middleware.rate_limit import queue_today_limit
from backend.models.schema import Branch, BranchVoice
from backend.services.audit_service import audit
from backend.services.wa_lifecycle import is_connected as whatsapp_is_connected

logger = structlog.get_logger()
router = APIRouter()

# Soniox is the sole TTS provider. A clinic's chosen catalog voice lives in
# branches.tts_voice; legacy values resolve to the configured Soniox default.
SONIOX_VOICES = tuple(
    {"voice_id": name, "display_name": name, "gender": gender, "kind": "catalog"}
    for name, gender in (
        ("Maya", "female"), ("Daniel", "male"), ("Noah", "male"),
        ("Nina", "female"), ("Emma", "female"), ("Jack", "male"),
        ("Adrian", "male"), ("Claire", "female"), ("Grace", "female"),
        ("Owen", "male"), ("Mina", "female"), ("Kenji", "male"),
        ("Rafael", "male"), ("Mateo", "male"), ("Lucia", "female"),
        ("Sofia", "female"), ("Oliver", "male"), ("Arthur", "male"),
        ("Isla", "female"), ("Victoria", "female"), ("Cooper", "male"),
        ("Mason", "male"), ("Ruby", "female"), ("Elise", "female"),
        ("Arjun", "male"), ("Rohan", "male"), ("Priya", "female"),
        ("Meera", "female"),
    )
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
    # WA MVP1 Task 8: connection status from Branch.wa_status (migration mm36)
    # — none/connected/disconnected/error. Set by the concierge link script
    # today; by Embedded Signup (Task 9) once shipped. NEVER expose
    # wa_token_enc or any token here — masked number only (RULE 9).
    whatsapp_status: str = "none"
    whatsapp_masked_number: str | None = None
    reminder_calls_enabled: bool = True
    followup_calls_enabled: bool = True
    whatsapp_reminder_ready: bool = False
    whatsapp_followup_ready: bool = False




def _masked_whatsapp_number(branch: Branch) -> str | None:
    """Last-4 only (RULE 9 — never the full number, never any token), and only
    once WhatsApp is actually connected. `Branch.whatsapp_number` holds a
    `pending-<uuid>` placeholder until a real number is linked — never mask
    that as if it were a phone number."""
    if not whatsapp_is_connected(branch):
        return None
    digits = "".join(c for c in (getattr(branch, "whatsapp_number", None) or "") if c.isdigit())
    return f"…{digits[-4:]}" if len(digits) >= 4 else None


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
    from backend.services.wa_readiness import purpose_readiness

    wa_ready = await purpose_readiness(branch, plan, ("reminder", "followup"))
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
        whatsapp_status=getattr(branch, "wa_status", None) or "none",
        whatsapp_masked_number=_masked_whatsapp_number(branch),
        reminder_calls_enabled=bool(getattr(branch, "reminder_calls_enabled", True)),
        followup_calls_enabled=bool(getattr(branch, "followup_calls_enabled", True)),
        whatsapp_reminder_ready=wa_ready["reminder"],
        whatsapp_followup_ready=wa_ready["followup"],
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
    if body.language is not None and body.language not in ALLOWED_LANGUAGES:
        raise HTTPException(status_code=422, detail=f"Language must be one of {ALLOWED_LANGUAGES}")
    if body.tts_voice is None and body.language is None:
        raise HTTPException(status_code=422, detail="Provide a voice or a language")

    result = await db.execute(select(Branch).where(Branch.id == uuid.UUID(branch_id)))
    branch = result.scalar_one_or_none()
    if branch is None:
        raise HTTPException(status_code=404, detail="Branch not found")

    if body.tts_voice is not None and body.tts_voice not in SONIOX_VOICE_IDS:
        owned_clone = (
            await db.execute(
                select(BranchVoice.id).where(
                    BranchVoice.branch_id == uuid.UUID(branch_id),
                    BranchVoice.provider_voice_id == body.tts_voice,
                    BranchVoice.status == "ready",
                )
            )
        ).scalar_one_or_none()
        if owned_clone is None:
            raise HTTPException(status_code=422, detail="Voice is not ready or does not belong to this clinic")

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

    clones = (
        await db.execute(
            select(BranchVoice).where(
                BranchVoice.branch_id == uuid.UUID(branch_id),
                BranchVoice.status == "ready",
                BranchVoice.provider_voice_id.is_not(None),
            )
        )
    ).scalars().all()
    clone_voices = [
        {
            "voice_id": voice.provider_voice_id,
            "display_name": voice.name,
            "gender": None,
            "kind": "clone",
            "languages": [lang],
        }
        for voice in clones
    ]
    clone_ids = {voice["voice_id"] for voice in clone_voices}
    current = getattr(branch, "tts_voice", None)
    if current not in SONIOX_VOICE_IDS and current not in clone_ids:
        from backend.config import settings as _settings
        current = _settings.soniox_tts_default_voice
    return {
        "language": lang,
        "current": current,
        "voices": [{**voice, "languages": [lang]} for voice in SONIOX_VOICES] + clone_voices,
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

    # Only questions still waiting on the doctor: once answered on the dashboard
    # they either joined the FAQ below or were deliberately kept out of it, so
    # repeating them here is noise (2026-08-02).
    asked = (
        await db.execute(
            select(ClinicQuestion)
            .where(
                ClinicQuestion.branch_id == uuid.UUID(branch_id),
                ClinicQuestion.answer.is_(None),
                ClinicQuestion.status != "dismissed",  # ignored, never asked again
            )
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


class QuestionAnswerIn(BaseModel):
    answer: str
    add_to_faq: bool = False


async def _recover_caller_phone(db: AsyncSession, branch_id: uuid.UUID, q) -> str | None:
    """The number to dial for a question logged BEFORE clinic_questions grew a
    caller_phone column (migration ll35, 2026-08-02) — those rows carry only
    caller_last4, so every answer landed on "unreachable" and no callback was
    ever placed (Vinay 2026-08-03: "call is not getting triggered").

    Recover it from the patient record, which usually still has it:
      1. the linked patient (branch-scoped — RULE 1);
      2. else patients in THIS branch whose phone ends with caller_last4, and
         ONLY when that resolves to a single number. Two different numbers
         share the last 4 digits often enough, and reading one patient's answer
         out to another is a DPDP incident — ambiguity fails closed.
    Returns None when nothing resolves; the caller keeps "unreachable"."""
    from backend.models.schema import Patient

    if q.patient_id:
        phone = (
            await db.execute(
                select(Patient.phone).where(
                    Patient.id == q.patient_id,
                    Patient.branch_id == branch_id,  # RULE 1: never cross-branch
                )
            )
        ).scalar_one_or_none()
        if phone:
            return phone

    last4 = (q.caller_last4 or "").strip()
    if not (len(last4) == 4 and last4.isdigit()):
        return None
    # DISTINCT: a family sharing one phone is several patient rows but a single
    # delivery address — that is not ambiguity. Two DIFFERENT numbers are.
    phones = (
        await db.execute(
            select(Patient.phone)
            .where(
                Patient.branch_id == branch_id,  # RULE 1
                Patient.phone.is_not(None),
                Patient.phone.like(f"%{last4}"),
            )
            .distinct()
            .limit(2)
        )
    ).scalars().all()
    return phones[0] if len(phones) == 1 else None


@router.get("/{branch_id}/questions")
async def list_questions(
    branch_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Questions callers asked that the AI could not answer (2026-08-02).
    Newest first; latest 50. Shows who asked so the clinic knows whose callback
    the doctor's answer is going to.

    Vinay 2026-08-03: ONLY still-unanswered questions. Once answered the item is
    handled — it either joined the FAQ (visible in Settings) or was deliberately
    kept out, and the callback is the job's problem — so leaving it here is
    clutter on a desk that should show only what still needs action. The row is
    KEPT in the database (the answer is a record); it is just not surfaced."""
    await assert_branch_access(current_user, branch_id, db)
    from backend.models.schema import ClinicQuestion, Patient

    rows = (
        await db.execute(
            select(ClinicQuestion, Patient.name)
            .outerjoin(Patient, Patient.id == ClinicQuestion.patient_id)
            .where(
                ClinicQuestion.branch_id == uuid.UUID(branch_id),
                ClinicQuestion.answer.is_(None),
                ClinicQuestion.status != "dismissed",  # ignored, never asked again
            )
            .order_by(ClinicQuestion.created_at.desc())
            .limit(50)
        )
    ).all()
    return {
        "questions": [
            {
                "id": str(q.id),
                "question": q.question,
                "answer": q.answer,
                "status": q.status,
                "added_to_faq": q.added_to_faq,
                "patient_name": name,
                "caller_phone": q.caller_phone,
                "caller_last4": q.caller_last4,
                "created_at": q.created_at.isoformat() if q.created_at else None,
                "answered_at": q.answered_at.isoformat() if q.answered_at else None,
            }
            for q, name in rows
        ],
        "pending": sum(1 for q, _ in rows if q.answer is None),
    }


@router.post("/{branch_id}/questions/{question_id}/answer")
@audit("branch.question_answered", resource_type="clinic_question")
async def answer_question(
    branch_id: str,
    question_id: str,
    body: QuestionAnswerIn,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """The doctor (or owner) answers a caller's question and decides whether it
    joins the FAQ (Vinay 2026-08-02). EITHER WAY the caller gets a callback: the
    answer is queued and question_callback_caller dials them and speaks it.

    Doctors may write here even though the FAQ editor is owner-only — Vinay's
    call: the doctor is the one who knows the answer."""
    await assert_branch_access(current_user, branch_id, db)
    from backend.models.schema import ClinicQuestion

    answer = " ".join((body.answer or "").split())
    if not answer:
        raise HTTPException(status_code=422, detail="Answer cannot be empty")
    if len(answer) > _FAQ_A_MAX:
        raise HTTPException(status_code=422, detail=f"Answer must be under {_FAQ_A_MAX} characters")
    q = (
        await db.execute(
            select(ClinicQuestion).where(
                ClinicQuestion.id == uuid.UUID(question_id),
                # RULE 1: id alone is not enough — the row must belong to the
                # branch this user is authorized on.
                ClinicQuestion.branch_id == uuid.UUID(branch_id),
            )
        )
    ).scalar_one_or_none()
    if q is None:
        raise HTTPException(status_code=404, detail="Question not found")

    faq_added = False
    if body.add_to_faq and not q.added_to_faq:
        branch = (
            await db.execute(select(Branch).where(Branch.id == uuid.UUID(branch_id)))
        ).scalar_one_or_none()
        if branch is None:
            raise HTTPException(status_code=404, detail="Branch not found")
        faq = list(getattr(branch, "faq", None) or [])
        if len(faq) >= _FAQ_MAX_ITEMS:
            raise HTTPException(
                status_code=422,
                detail=f"FAQ is full ({_FAQ_MAX_ITEMS} entries) — remove one in Settings first",
            )
        faq.append({"q": q.question[:_FAQ_Q_MAX], "a": answer})
        branch.faq = faq  # reassign — JSONB change tracking
        faq_added = True

    q.answer = answer
    q.answered_at = datetime.now(timezone.utc)
    q.added_to_faq = q.added_to_faq or faq_added
    # Pre-ll35 rows carry only caller_last4 — recover the number from the
    # patient record and PERSIST it, so the callback job (which reads
    # caller_phone) dials on its next tick and the lookup happens once.
    recovered = False
    if not q.caller_phone:
        found = await _recover_caller_phone(db, uuid.UUID(branch_id), q)
        if found:
            q.caller_phone = found
            recovered = True
    # Still no number to dial (walk-in-style unknown caller, or an ambiguous
    # last-4) → nothing to call back.
    q.status = "answered" if q.caller_phone else "unreachable"

    # A question that ARRIVED on WhatsApp is answered on WhatsApp. Someone who
    # chose to type did so to avoid a phone call, and ringing them with the
    # answer ignores that choice (Vinay 2026-08-04). Only if the message cannot
    # be delivered — most often Meta's 24-hour service window having closed
    # since they wrote in — do we fall back to the callback the voice path uses.
    if q.status == "answered" and getattr(q, "channel", "voice") == "whatsapp":
        from backend.services import wa_whatsapp_answer

        if await wa_whatsapp_answer.reply(db, uuid.UUID(branch_id), q, answer):
            q.status = "replied"  # terminal: the callback job skips it

    await db.commit()
    if q.status == "answered":
        # Wake the callback job's gate so the patient is dialed on the next
        # 5-min tick instead of waiting out the safety ceiling (#299 pattern).
        from backend.jobs import wake_gate

        await wake_gate.clear_next_at("question_callbacks")
    logger.info(
        "clinic_question_answered",
        branch_id=branch_id,
        question_id=question_id,
        added_to_faq=q.added_to_faq,
        callback=q.status,
        phone_recovered=recovered,
        phone_last4=(q.caller_phone or "")[-4:] or None,  # RULE 9: last-4 in logs
    )
    request.state.audit_resource_id = str(q.id)
    request.state.audit_branch_id = branch_id
    # IDs and flags only — never the question, the answer, or the number.
    request.state.audit_metadata = {
        "added_to_faq": q.added_to_faq, "callback": q.status,
    }
    return {
        "id": str(q.id),
        "status": q.status,
        "added_to_faq": q.added_to_faq,
        "callback_queued": q.status == "answered",
    }


@router.post("/{branch_id}/questions/{question_id}/dismiss")
@audit("branch.question_dismissed", resource_type="clinic_question")
async def dismiss_question(
    branch_id: str,
    question_id: str,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Drop a question without answering it — nothing reaches the caller.

    Vinay 2026-08-04: "some sarcastic questions are also dropping... include
    option to delete question without answering, which will never go to user
    and will be dropped." Answering was the only exit, so a joke or a
    duplicate sat on the desk until someone wrote a reply that then got
    PHONED to the caller.

    The row is KEPT (it is a record of what callers ask, and retention/erasure
    own its lifetime) — it just leaves the desk and the Settings backlog.
    `status='dismissed'` with `answer` still NULL is what makes it terminal:
    the callback job only ever selects `status == 'answered'`, so a dismissed
    question can never be dialed.
    """
    await assert_branch_access(current_user, branch_id, db)
    from backend.models.schema import ClinicQuestion

    q = (
        await db.execute(
            select(ClinicQuestion).where(
                ClinicQuestion.id == uuid.UUID(question_id),
                ClinicQuestion.branch_id == uuid.UUID(branch_id),  # RULE 1
            )
        )
    ).scalar_one_or_none()
    if q is None:
        raise HTTPException(status_code=404, detail="Question not found")
    if q.answer:
        # Already answered means a callback is queued or done. Dismissing then
        # would imply we can unsend it, and we cannot.
        raise HTTPException(
            status_code=409, detail="Already answered — the caller has been replied to"
        )

    q.status = "dismissed"
    await db.commit()
    logger.info(
        "clinic_question_dismissed",
        branch_id=branch_id,
        question_id=question_id,
        phone_last4=(q.caller_phone or "")[-4:] or None,  # RULE 9
    )
    request.state.audit_resource_id = str(q.id)
    request.state.audit_branch_id = branch_id
    request.state.audit_metadata = {"status": "dismissed"}
    return {"id": str(q.id), "status": q.status}


@router.get("/{branch_id}/messages")
async def list_messages(
    branch_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Caller messages the voice agent took for the doctor/clinic (#349).
    Urgent first, newest first; latest 50.

    Vinay 2026-08-03: ONLY messages still awaiting action — a message marked
    done has been handled, so it leaves the dashboard. The row is KEPT in the
    database (retention/erasure own its lifetime) and stays visible in the
    patient's treatment thread; it is just off the desk."""
    await assert_branch_access(current_user, branch_id, db)
    from backend.models.schema import Patient, PatientMessage

    rows = (
        await db.execute(
            select(PatientMessage, Patient.name)
            .outerjoin(Patient, Patient.id == PatientMessage.patient_id)
            .where(
                PatientMessage.branch_id == uuid.UUID(branch_id),
                PatientMessage.status == "pending",
            )
            .order_by(
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


class TelephonySettings(BaseModel):
    """Non-secret view of a branch's telephony config. The SIP password is NEVER
    returned — only whether one is set."""
    vobiz_subaccount_id: str | None = None
    vobiz_sip_username: str | None = None
    vobiz_sip_domain: str | None = None
    shared_outbound_trunk_configured: bool = False
    has_sip_password: bool = False


def _telephony_payload(branch: Branch) -> TelephonySettings:
    from backend.services.telephony import (
        OutboundTrunkIsolationError,
        shared_outbound_trunk_id,
    )

    try:
        shared_configured = bool(shared_outbound_trunk_id())
    except OutboundTrunkIsolationError:
        shared_configured = False

    return TelephonySettings(
        vobiz_subaccount_id=getattr(branch, "vobiz_subaccount_id", None),
        vobiz_sip_username=getattr(branch, "vobiz_sip_username", None),
        vobiz_sip_domain=getattr(branch, "vobiz_sip_domain", None),
        shared_outbound_trunk_configured=shared_configured,
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

    for field in ("vobiz_subaccount_id", "vobiz_sip_username", "vobiz_sip_domain"):
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
    reminder_calls_enabled: bool | None = None
    followup_calls_enabled: bool | None = None

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
        # Serialize the check with any concurrent onboarding transaction. The
        # unique index remains the last line of defence, but this lock turns a
        # race from an IntegrityError/500 into the intended 409 response.
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"did:{new_did}"},
        )
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

    requested_channels = {
        "reminder": body.reminder_calls_enabled,
        "followup": body.followup_calls_enabled,
    }
    if any(value is False for value in requested_channels.values()):
        plan, _ = await _org_plan_and_start(db, branch)
        from backend.services.wa_readiness import purpose_readiness

        readiness = await purpose_readiness(branch, plan, tuple(requested_channels))
        unavailable = [
            purpose for purpose, enabled in requested_channels.items()
            if enabled is False and not readiness[purpose]
        ]
        if unavailable:
            raise HTTPException(
                status_code=409,
                detail=(
                    "WhatsApp must be connected, entitled, and have an approved "
                    f"{', '.join(unavailable)} template before phone calls can be disabled."
                ),
            )

    old_did = branch.did_number  # capture before mutate (G9 trunk cleanup)
    for field in (
        "name", "address", "city", "clinic_phone",
        "emergency_contact", "google_calendar_id", "did_number",
    ):
        value = getattr(body, field)
        if value is not None:
            setattr(branch, field, value.strip() or None)
    if body.reminder_calls_enabled is not None:
        branch.reminder_calls_enabled = body.reminder_calls_enabled
    if body.followup_calls_enabled is not None:
        branch.followup_calls_enabled = body.followup_calls_enabled
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
    if body.did_number is not None:
        from backend.services.livekit_sip import (
            remove_did_from_inbound_trunk,
            remove_did_from_outbound_trunk,
            sync_did_to_inbound_trunk,
            sync_did_to_outbound_trunk,
        )

        # G9: if the DID actually changed, pull the OLD number off the trunk
        # first so a future reassignment of it can't route into our system.
        removal_ok = True
        if old_did and old_did != branch.did_number:
            old_inbound = await remove_did_from_inbound_trunk(old_did)
            old_outbound = await remove_did_from_outbound_trunk(old_did)
            removal_ok = old_inbound["ok"] and old_outbound["ok"]

        if branch.did_number:
            inbound_sync = await sync_did_to_inbound_trunk(branch.did_number)
            outbound_sync = await sync_did_to_outbound_trunk(branch.did_number)
            did_wired = removal_ok and inbound_sync["ok"] and outbound_sync["ok"]
        else:
            # Clearing a DID is a successful unwire operation. The hourly exact
            # reconciliation is the retry path if either best-effort removal
            # above failed.
            inbound_sync = {"ok": True, "detail": "cleared"}
            outbound_sync = {"ok": True, "detail": "cleared"}
            did_wired = removal_ok
        if not did_wired:
            logger.warning(
                "did_wire_pending", branch_id=branch_id,
                inbound=inbound_sync["detail"], outbound=outbound_sync["detail"],
            )

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


class WaTemplateCreate(BaseModel):
    """WA MVP1 Task 10 — a clinic-authored template submitted for Meta review.
    Validation (name shape, sequential placeholders, example coverage) is
    enforced in wa_template_admin BEFORE Meta ever sees the payload."""
    name: str = Field(..., min_length=1, max_length=512)
    category: str = "UTILITY"
    body: str = Field(..., min_length=1, max_length=1024)
    examples: list[str] = Field(default_factory=list, max_length=10)
    buttons: list[str] = Field(default_factory=list, max_length=3)
    language: str = "en"


@router.get("/{branch_id}/whatsapp/templates")
async def list_whatsapp_templates(
    branch_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """This clinic's own WhatsApp templates, from ITS WABA — never the
    platform token, or a clinic would see another clinic's templates
    (RULE 1). A branch with no WABA connected yet just has none."""
    await assert_branch_access(current_user, branch_id, db)
    branch = (
        await db.execute(select(Branch).where(Branch.id == uuid.UUID(branch_id)))
    ).scalar_one_or_none()
    if branch is None:
        raise HTTPException(status_code=404, detail="Branch not found")

    from backend.services import wa_template_admin

    try:
        return await wa_template_admin.list_templates(branch)
    except wa_template_admin.NotConnected:
        return []
    except wa_template_admin.TemplateAdminError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@router.post("/{branch_id}/whatsapp/templates", status_code=201)
@audit("branch.wa_template_created", resource_type="branch")
async def create_whatsapp_template(
    branch_id: str,
    body: WaTemplateCreate,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Submit a clinic-authored template for Meta review. org_admin only —
    a WhatsApp template is brand-facing, same bar as the FAQ/voice."""
    await assert_branch_access(current_user, branch_id, db)
    _require_org_admin(current_user)
    if not settings.whatsapp_self_serve_live:
        raise HTTPException(status_code=409, detail="WhatsApp onboarding is coming soon")

    branch = (
        await db.execute(select(Branch).where(Branch.id == uuid.UUID(branch_id)))
    ).scalar_one_or_none()
    if branch is None:
        raise HTTPException(status_code=404, detail="Branch not found")

    from backend.services import wa_template_admin

    try:
        result = await wa_template_admin.create_template(
            branch,
            name=body.name,
            category=body.category,
            body=body.body,
            examples=body.examples,
            buttons=body.buttons,
            language=body.language,
        )
    except wa_template_admin.TemplateAdminError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    request.state.audit_resource_id = branch_id
    request.state.audit_user_id = current_user.user_id
    request.state.audit_branch_id = branch_id
    # RULE 9 / PII_DENYLIST: no "name" key (denylist matches "name" as a
    # substring) — category alone is enough forensic context.
    request.state.audit_metadata = {"category": body.category.upper()}
    # The purpose -> template map is cached for an hour; drop it so a clinic
    # that just added, say, its cancellation template starts using it on the
    # next send rather than after the TTL expires.
    from backend.services import wa_template_registry

    await wa_template_registry.invalidate(branch.id)
    logger.info("wa_template_submitted", branch_id=branch_id)
    return result


@router.post("/{branch_id}/whatsapp/templates/system")
@audit("branch.wa_system_templates_installed", resource_type="branch")
async def install_whatsapp_system_templates(
    branch_id: str,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Idempotently install the patient-event templates on this clinic WABA."""
    await assert_branch_access(current_user, branch_id, db)
    _require_org_admin(current_user)
    branch = (
        await db.execute(select(Branch).where(Branch.id == uuid.UUID(branch_id)))
    ).scalar_one_or_none()
    if branch is None:
        raise HTTPException(status_code=404, detail="Branch not found")

    from backend.services import wa_template_admin, wa_template_registry

    try:
        result = await wa_template_admin.ensure_system_templates(branch)
    except wa_template_admin.TemplateAdminError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    await wa_template_registry.invalidate(branch.id)
    request.state.audit_resource_id = branch_id
    return result


@router.delete("/{branch_id}/whatsapp/templates/{name}")
@audit("branch.wa_template_deleted", resource_type="branch")
async def delete_whatsapp_template(
    branch_id: str,
    name: str,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """org_admin only. Required system templates are wired into live send
    paths and can never be deleted here (409) — see wa_template_admin."""
    await assert_branch_access(current_user, branch_id, db)
    _require_org_admin(current_user)

    branch = (
        await db.execute(select(Branch).where(Branch.id == uuid.UUID(branch_id)))
    ).scalar_one_or_none()
    if branch is None:
        raise HTTPException(status_code=404, detail="Branch not found")

    from backend.services import wa_template_admin

    try:
        await wa_template_admin.delete_template(branch, name)
    except wa_template_admin.TemplateAdminError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    request.state.audit_resource_id = branch_id
    request.state.audit_user_id = current_user.user_id
    request.state.audit_branch_id = branch_id
    from backend.services import wa_template_registry

    await wa_template_registry.invalidate(branch.id)
    logger.info("wa_template_deleted_route", branch_id=branch_id)
    return {"deleted": True}


# ── WhatsApp Embedded Signup — Tech Provider connect (WA MVP1 Task 9) ───────
# Self-serve alternative to the concierge PATCH /admin/branches/{id}/whatsapp
# (backend/routers/admin.py, super_admin-only): here the clinic OWNER connects
# its OWN WABA after Meta's Embedded Signup JS flow hands the frontend a
# one-time `code` plus the `waba_id`/`phone_number_id` from the session_info
# event. org_admin only — connecting the clinic's WhatsApp identity is an
# owner-level decision (same bar as telephony/voice/FAQ).


class WaConnectBody(BaseModel):
    code: str = Field(..., min_length=10, max_length=4000)
    waba_id: str = Field(..., min_length=1, max_length=32)
    phone_number_id: str = Field(..., min_length=1, max_length=32)
    flow_event: Literal["FINISH", "FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING"]
    business_id: str | None = Field(default=None, max_length=32)

    @field_validator("waba_id", "phone_number_id", "business_id")
    @classmethod
    def _numeric_meta_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = (value or "").strip()
        if not value.isdigit():
            raise ValueError("Must be a numeric Meta id")
        return value


# ── WhatsApp chats — read-only view of what the bot said to patients ────────
# Vinay 2026-08-02: "we also need whatsapp pages to choose template, track
# chats etc". Templates are above; this is the tracking half.
#
# Read-only on purpose. A staff "reply" box would collide with the bot: under
# Coexistence the clinic's own WhatsApp app is still live on the same number,
# so a receptionist already has a place to type — their phone. Adding a second
# one here would produce two replies to one patient message.
#
# RULE 1: every query branch-scoped, and assert_branch_access additionally
# locks super_admin out entirely (DPDP: Vinay is a Data Processor, patient
# chat content is clinic PII).

_CHAT_PAGE_SIZE = 50


@router.get("/{branch_id}/whatsapp/chats")
async def list_whatsapp_chats(
    branch_id: str,
    limit: int = _CHAT_PAGE_SIZE,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Conversation list, most recently active first.

    Returns a PREVIEW only (last turn, truncated) — the full transcript costs
    a second request, so opening the page does not pull every clinic
    conversation's message history into a browser at once.
    """
    await assert_branch_access(current_user, branch_id, db)
    from backend.models.schema import WhatsAppSession

    rows = (
        await db.execute(
            select(WhatsAppSession)
            .join(Branch, Branch.id == WhatsAppSession.branch_id)
            .where(
                WhatsAppSession.branch_id == uuid.UUID(branch_id),  # RULE 1
                Branch.wa_status == 'connected',
                Branch.wa_phone_number_id.is_not(None),
            )
            .order_by(WhatsAppSession.updated_at.desc().nullslast())
            .limit(max(1, min(int(limit or _CHAT_PAGE_SIZE), 200)))
        )
    ).scalars().all()

    out: list[dict] = []
    for row in rows:
        turns = ((row.session_data or {}).get("turns") or [])
        last = turns[-1] if turns else {}
        out.append({
            "phone": row.patient_phone,
            "phone_last4": (row.patient_phone or "")[-4:],
            "turn_count": len(turns),
            "last_role": last.get("role"),
            "last_text": (last.get("text") or "")[:120],
            "last_at": last.get("at"),
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        })
    return out


@router.get("/{branch_id}/whatsapp/chats/{phone}")
async def get_whatsapp_chat(
    branch_id: str,
    phone: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Full stored transcript for one patient thread at THIS branch.

    Only what wa_session already retains (last N turns, expiring rows) — this
    route reads that store, it never extends retention, so the figures quoted
    in docs/legal/*.md stay accurate.
    """
    await assert_branch_access(current_user, branch_id, db)
    from backend.models.schema import WhatsAppSession

    row = (
        await db.execute(
            select(WhatsAppSession)
            .join(Branch, Branch.id == WhatsAppSession.branch_id)
            .where(
                WhatsAppSession.branch_id == uuid.UUID(branch_id),  # RULE 1
                WhatsAppSession.patient_phone == phone,
                Branch.wa_status == 'connected',
                Branch.wa_phone_number_id.is_not(None),
            )
        )
    ).scalars().first()
    if row is None:
        raise HTTPException(status_code=404, detail="No conversation found")
    return {
        "phone": row.patient_phone,
        "phone_last4": (row.patient_phone or "")[-4:],
        "turns": (row.session_data or {}).get("turns") or [],
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.get("/{branch_id}/whatsapp/signup-config")
async def get_whatsapp_signup_config(
    branch_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """What the browser needs to open Meta's Embedded Signup popup.

    Only app_id / config_id / graph_version — all three are PUBLIC by design
    (they ship inside Meta's own JS snippet). The secret half of the pair,
    `meta_app_secret`, stays server-side and is used solely in the
    authorization-code exchange (wa_connect._exchange_code). RULE 9: nothing
    here is a credential, so nothing here is logged either way.

    Served from settings rather than baked into the frontend bundle so that
    moving to a different Meta app — or fixing a wrong config id — is an env
    change, not a rebuild-and-redeploy of the PWA.

    `configured` false means the Connect button must say so plainly instead of
    opening a popup Meta would reject with an unhelpful error.
    """
    await assert_branch_access(current_user, branch_id, db)
    _require_org_admin(current_user)
    return {
        "app_id": settings.meta_app_id,
        "config_id": settings.meta_config_id,
        "graph_version": settings.meta_graph_version,
        "embedded_signup_version": 4,
        "feature_type": "whatsapp_business_app_onboarding",
        "required_permissions": [
            "whatsapp_business_management",
            "whatsapp_business_messaging",
        ],
        "configured": bool(
            settings.meta_app_id
            and settings.meta_app_secret
            and settings.meta_config_id
            and settings.meta_webhook_verify_token
            and (settings.meta_graph_version or "").startswith("v")
        ),
    }


@router.get("/{branch_id}/whatsapp/connect")
async def get_whatsapp_connection(
    branch_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Connection status for the Settings UI. Any branch user can read this
    (mirrors GET /{branch_id}/settings) — only connect/disconnect are
    owner-only. RULE 9: never returns wa_token_enc or any part of a token."""
    await assert_branch_access(current_user, branch_id, db)
    branch = (
        await db.execute(select(Branch).where(Branch.id == uuid.UUID(branch_id)))
    ).scalar_one_or_none()
    if branch is None:
        raise HTTPException(status_code=404, detail="Branch not found")
    connected_at = getattr(branch, "wa_connected_at", None)
    from backend.services.wa_connect import public_onboarding

    return {
        "branch_id": branch_id,
        "connected": whatsapp_is_connected(branch),
        "wa_status": getattr(branch, "wa_status", None) or "none",
        "wa_waba_id": getattr(branch, "wa_waba_id", None),
        "wa_verified_name": getattr(branch, "wa_verified_name", None),
        "wa_phone_number_id": getattr(branch, "wa_phone_number_id", None),
        "wa_connected_at": connected_at.isoformat() if connected_at else None,
        "onboarding": public_onboarding(branch),
    }


async def _auto_install_wa_system_templates(branch) -> dict:
    """Best-effort onboarding step; the explicit website button can retry."""
    try:
        from backend.services import wa_template_admin, wa_template_registry

        result = await wa_template_admin.ensure_system_templates(branch)
        await wa_template_registry.invalidate(branch.id)
        return result
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "wa_system_template_install_failed",
            branch_id=str(branch.id), error=str(exc)[:160],
        )
        return {
            "created": [], "existing": [],
            "errors": [{
                "name": "system",
                "detail": "Retry from the WhatsApp templates page.",
            }],
        }


@router.post("/{branch_id}/whatsapp/connect", status_code=201)
@audit("branch.wa_connected", resource_type="branch")
async def connect_whatsapp(
    branch_id: str,
    body: WaConnectBody,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Embedded Signup callback: the clinic owner connects ITS OWN WABA.
    org_admin only. Exchanges the authorization code for a business token,
    subscribes our app to the WABA's webhooks (mandatory — see wa_connect
    docstring), best-effort registers the number for Cloud API, and stores
    the encrypted token + connection metadata on the branch.

    RULE 1: wa_waba_id is UNIQUE — a WABA already claimed by another branch
    is a clean 409, checked BEFORE any Graph call (cheap, no wasted Meta
    round-trip) and again at commit (IntegrityError -> 409) as a race guard.
    RULE 9: the body carries `code` (one-time secret) but it is never logged
    — only branch_id / waba_id / status appear in any log line.
    """
    await assert_branch_access(current_user, branch_id, db)
    _require_org_admin(current_user)
    if not settings.whatsapp_self_serve_live:
        raise HTTPException(status_code=409, detail="WhatsApp onboarding is coming soon")

    branch = (
        await db.execute(select(Branch).where(Branch.id == uuid.UUID(branch_id)))
    ).scalar_one_or_none()
    if branch is None:
        raise HTTPException(status_code=404, detail="Branch not found")

    clash = (
        await db.execute(
            select(Branch).where(
                Branch.wa_waba_id == body.waba_id, Branch.id != branch.id,
            )
        )
    ).scalar_one_or_none()
    if clash is not None:
        logger.warning(
            "wa_waba_already_linked", branch_id=branch_id, waba_id=body.waba_id,
        )
        raise HTTPException(
            status_code=409,
            detail="This WhatsApp Business Account is already connected to another clinic.",
        )

    from backend.services import wa_connect

    try:
        result = await wa_connect.connect_branch(
            branch, code=body.code, waba_id=body.waba_id,
            phone_number_id=body.phone_number_id,
            flow_event=body.flow_event, business_id=body.business_id,
        )
    except wa_connect.WaConnectError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    from sqlalchemy.exc import IntegrityError

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        logger.warning(
            "wa_waba_already_linked", branch_id=branch_id, waba_id=body.waba_id,
        )
        raise HTTPException(
            status_code=409,
            detail="This WhatsApp Business Account is already connected to another clinic.",
        )

    request.state.audit_resource_id = branch_id
    request.state.audit_user_id = current_user.user_id
    request.state.audit_branch_id = branch_id
    request.state.audit_metadata = {"waba_id": body.waba_id, "status": branch.wa_status}

    result["templates"] = await _auto_install_wa_system_templates(branch)
    logger.info(
        "wa_branch_connected", branch_id=branch_id, waba_id=body.waba_id,
        status=branch.wa_status, phone_registered=result.get("registered"),
    )
    return {
        "branch_id": branch_id,
        "wa_status": branch.wa_status,
        "wa_waba_id": branch.wa_waba_id,
        "wa_verified_name": branch.wa_verified_name,
        "wa_connected_at": branch.wa_connected_at.isoformat() if branch.wa_connected_at else None,
        "phone_registered": result.get("registered"),
        "onboarding": result.get("onboarding"),
        "templates": result.get("templates"),
    }


@router.post("/{branch_id}/whatsapp/connect/manual", status_code=410, include_in_schema=False)
@audit("branch.wa_connected_manual", resource_type="branch")
async def connect_whatsapp_manual(
    branch_id: str,
    body: dict,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Connect by pasting the IDs from Meta's API Setup screen instead of
    walking through Embedded Signup. org_admin only, same as the popup route.

    Why it exists: Embedded Signup cannot run until our Meta app is published
    Live, and a clinic on a partner-managed WABA may never get that popup at
    all. Without this the clinic page had no way to link a number, and the
    only path was a super_admin curl.

    RULE 1: wa_waba_id is UNIQUE — the clash is checked before any Graph call
    and again at commit, exactly as in the Embedded Signup route.
    RULE 9: `access_token` is never logged, not even truncated; it is
    Fernet-encrypted onto the branch by wa_connect and only branch_id /
    waba_id / status appear in any log line or audit row.
    """
    raise HTTPException(
        status_code=410,
        detail="Manual access-token entry has been retired. Use Meta Embedded Signup v4.",
    )


@router.post("/{branch_id}/whatsapp/connect/sync")
@audit("branch.wa_sync_retried", resource_type="branch")
async def retry_whatsapp_sync(
    branch_id: str,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await assert_branch_access(current_user, branch_id, db)
    _require_org_admin(current_user)
    branch = (
        await db.execute(select(Branch).where(Branch.id == uuid.UUID(branch_id)))
    ).scalar_one_or_none()
    if branch is None:
        raise HTTPException(status_code=404, detail="Branch not found")
    from backend.services import wa_connect

    try:
        onboarding = await wa_connect.retry_coexistence_sync(branch)
    except wa_connect.WaConnectError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    await db.commit()
    request.state.audit_resource_id = branch_id
    request.state.audit_user_id = current_user.user_id
    request.state.audit_branch_id = branch_id
    return {"branch_id": branch_id, "onboarding": onboarding}


@router.post("/{branch_id}/whatsapp/connect/payment-confirmed")
@audit("branch.wa_payment_confirmed", resource_type="branch")
async def confirm_whatsapp_payment(
    branch_id: str,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Record the clinic owner's confirmation of Meta's required payment step."""
    await assert_branch_access(current_user, branch_id, db)
    _require_org_admin(current_user)
    branch = (
        await db.execute(select(Branch).where(Branch.id == uuid.UUID(branch_id)))
    ).scalar_one_or_none()
    if branch is None:
        raise HTTPException(status_code=404, detail="Branch not found")
    if not whatsapp_is_connected(branch):
        raise HTTPException(status_code=409, detail="Connect WhatsApp before confirming payment.")
    from backend.services.wa_connect import confirm_payment_method

    onboarding = confirm_payment_method(branch)
    await db.commit()
    request.state.audit_resource_id = branch_id
    request.state.audit_user_id = current_user.user_id
    request.state.audit_branch_id = branch_id
    return {"branch_id": branch_id, "onboarding": onboarding}


@router.delete("/{branch_id}/whatsapp/connect")
@audit("branch.wa_disconnected", resource_type="branch")
async def disconnect_whatsapp(
    branch_id: str,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Clear this clinic's stored WhatsApp credentials AND its stored
    conversations. org_admin only.

    Clears wa_phone_number_id too (not just the token) so wa_service.wa_enabled
    fails closed immediately rather than reporting a stale linked-but-tokenless
    state. Does not call Meta to revoke the subscription — the clinic can
    reconnect later through the same flow.

    The WhatsApp sessions go with the credentials. Those rows exist only to let
    the assistant follow a patient across several messages on a channel this
    clinic no longer runs; once the number is disconnected there is no purpose
    left to hold them under, and leaving them meant the Conversations page kept
    serving patient message text after the clinic had switched WhatsApp off.
    Deletion is per-branch (RULE 1) and happens in the same transaction as the
    credential clear, so we can never end up disconnected-but-still-storing.

    Scoped to whatsapp_sessions deliberately. ClinicQuestion and PatientMessage
    carry a callback promise to a patient and record no channel, so most of
    them are voice-originated — deleting those here would silently destroy work
    the clinic still owes someone.
    """
    await assert_branch_access(current_user, branch_id, db)
    _require_org_admin(current_user)

    branch = (
        await db.execute(select(Branch).where(Branch.id == uuid.UUID(branch_id)))
    ).scalar_one_or_none()
    if branch is None:
        raise HTTPException(status_code=404, detail="Branch not found")

    from backend.services import wa_connect
    from backend.services.wa_lifecycle import (
        disconnect_branch,
        invalidate_connection_caches,
    )

    meta_unsubscribed = await wa_connect.unsubscribe_branch(branch)
    result = await disconnect_branch(db, branch)
    await db.commit()
    await invalidate_connection_caches(branch.id)

    request.state.audit_resource_id = branch_id
    request.state.audit_user_id = current_user.user_id
    request.state.audit_branch_id = branch_id
    # RULE 9: a count, never a phone number or any message text.
    request.state.audit_metadata = {
        "sessions_purged": result.conversations_deleted,
        "deliveries_cancelled": result.deliveries_cancelled,
        "meta_unsubscribed": meta_unsubscribed,
    }

    logger.info(
        "wa_branch_disconnected",
        branch_id=branch_id,
        sessions_purged=result.conversations_deleted,
        deliveries_cancelled=result.deliveries_cancelled,
    )
    return {
        "branch_id": branch_id,
        "connected": False,
        "wa_status": branch.wa_status,
        "wa_waba_id": None,
        "wa_verified_name": None,
        "wa_phone_number_id": None,
        "wa_connected_at": None,
        "conversations_deleted": result.conversations_deleted,
        "deliveries_cancelled": result.deliveries_cancelled,
        "meta_unsubscribed": meta_unsubscribed,
    }


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
    removed_token_version = int(target.token_version or 0)
    await db.execute(User.__table__.delete().where(User.id == uid))
    await db.commit()
    expiry = int((datetime.now(timezone.utc) + timedelta(hours=settings.jwt_expire_hours)).timestamp())
    await revoke_user_version(user_id, removed_token_version, expiry)
    request.state.audit_resource_id = user_id
    request.state.audit_user_id = current_user.user_id
    request.state.audit_branch_id = branch_id
    logger.info("staff_removed", branch_id=branch_id, removed=user_id[-4:])
    return {"deleted": True, "user_id": user_id}

"""Support: KB read + grounded chatbot that auto-logs a ticket per chat.

RULE 1: bot has no clinic-data access; authed tickets carry the caller's org,
and ticket reads are WHERE org_id scoped.
RULE 8: bot failure returns a safe refusal, never a 500.
RULE 9: log ticket/message IDs, never bodies.
"""
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.database import get_db
from backend.middleware.auth_middleware import (
    CurrentUser,
    get_current_user,
    optional_current_user,
    require_support_admin,
    require_support_staff,
)
from backend.middleware.rate_limit import default_limit
from backend.models.schema import SupportMessage, SupportTicket, User
from backend.services import support_bot, support_email, support_kb, support_macros
from backend.services.turnstile import verify_turnstile
from backend.middleware.rate_limit import client_ip


async def _guard_anonymous(request: Request, user) -> None:
    """Turnstile applies ONLY to anonymous callers — a logged-in clinic user is
    already authenticated, and the client never attaches a Turnstile token on
    support routes. Bot-abuse protection is for the public path; authed calls
    rely on default_limit. 403 if an anonymous caller fails Turnstile (when it's
    enforced; feature-off in dev/tests → always passes)."""
    if user is None:
        token = request.headers.get("x-turnstile-token")
        if not await verify_turnstile(token, client_ip(request)):
            raise HTTPException(status_code=403, detail="captcha_failed")

logger = structlog.get_logger()
router = APIRouter()
_ANON_SESSION_COOKIE = "vachanam_support_session"

# SLA target hours by priority — sla_due_at = created_at + hours[priority].
_SLA_HOURS = {"urgent": 4, "high": 8, "normal": 24, "low": 72}


def _sla_due(priority: str) -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=_SLA_HOURS.get(priority, 24))


class ChatTurn(BaseModel):
    role: str = Field("user", max_length=16)
    content: str = Field("", max_length=2000)


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=20)
    ticket_id: uuid.UUID | None = None


@router.get("/kb")
async def get_kb(request: Request):
    user = await optional_current_user(request)
    audience = "clinic" if user and user.org_id else "public"
    return {"audience": audience, "markdown": support_kb.kb_text(audience)}


@router.post("/chat", dependencies=[Depends(default_limit)])
async def chat(
    body: ChatRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    user = await optional_current_user(request)
    await _guard_anonymous(request, user)  # Turnstile for anonymous only
    audience = "clinic" if user and user.org_id else "public"
    result = await support_bot.answer(
        body.question, [t.model_dump() for t in body.history], audience,
        plan=None,  # RULE 1: bot stays clinic-data-free in Phase 1
    )

    # One ticket per chat SESSION: reuse the caller's ticket if supplied, else open one.
    ticket = None
    is_new = False
    caller_org = str((user.org_id if user else None) or "")
    anonymous_session_id = None if user else request.cookies.get(_ANON_SESSION_COOKIE)
    if body.ticket_id:
        ticket = (
            await db.execute(select(SupportTicket).where(SupportTicket.id == body.ticket_id))
        ).scalar_one_or_none()
        if ticket and (
            (user and str(ticket.org_id or "") != caller_org)
            or (
                not user
                and (
                    not anonymous_session_id
                    or ticket.anonymous_session_id != anonymous_session_id
                )
            )
        ):
            ticket = None  # not this caller's ticket → open a fresh one
    if ticket is None:
        if not user and not anonymous_session_id:
            anonymous_session_id = secrets.token_urlsafe(32)
        ticket = SupportTicket(
            org_id=(user.org_id if user else None),
            anonymous_session_id=anonymous_session_id,
            email=(user.email if user else "anonymous@vachanam.in"),
            subject=body.question[:200],
            category="other",
            status="ai_resolved" if result["answered"] else "open",
            priority="normal",
            source="in_app" if (user and user.org_id) else "public_chat",
            sla_due_at=_sla_due("normal"),
        )
        db.add(ticket)
        await db.flush()
        is_new = True
    elif not result["answered"] and ticket.status == "ai_resolved":
        ticket.status = "open"  # a later unanswered turn re-opens for a human

    db.add_all([
        SupportMessage(ticket_id=ticket.id, sender="user", body=body.question),
        SupportMessage(ticket_id=ticket.id, sender="bot", body=result["answer"]),
    ])
    await db.commit()
    if not user and anonymous_session_id:
        response.set_cookie(
            _ANON_SESSION_COOKIE,
            anonymous_session_id,
            max_age=30 * 24 * 3600,
            httponly=True,
            secure=settings.app_env == "production",
            samesite="lax",
        )
    logger.info(
        "support_chat", ticket_id=str(ticket.id), answered=result["answered"],
        org_id=str(ticket.org_id) if ticket.org_id else None,
    )
    # ONE team email per NEW ticket that needs a human (AI couldn't answer).
    # AI-resolved chats never email (Vinay 2026-07-12, Resend quota). RULE 8.
    if is_new and ticket.status == "open":
        await support_email.notify_new_ticket(ticket.id, ticket.subject, ticket.email)
    return {"answer": result["answer"], "answered": result["answered"],
            "ticket_id": str(ticket.id)}


async def _my_ticket(ticket_id: uuid.UUID, user: CurrentUser, db: AsyncSession) -> SupportTicket:
    """Fetch a ticket ONLY if it belongs to the caller's org (RULE 1). 404 else."""
    t = (
        await db.execute(
            select(SupportTicket).where(
                SupportTicket.id == ticket_id, SupportTicket.org_id == user.org_id
            )
        )
    ).scalar_one_or_none()
    if t is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return t


@router.get("/tickets")
async def list_my_tickets(user: CurrentUser = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(
            select(SupportTicket).where(SupportTicket.org_id == user.org_id)
            .order_by(SupportTicket.created_at.desc())
        )
    ).scalars().all()
    return [{"id": str(t.id), "subject": t.subject, "status": t.status,
             "category": t.category, "created_at": t.created_at.isoformat()} for t in rows]


@router.get("/tickets/{ticket_id}")
async def get_ticket(ticket_id: uuid.UUID, user: CurrentUser = Depends(get_current_user),
                     db: AsyncSession = Depends(get_db)):
    t = await _my_ticket(ticket_id, user, db)
    return {"id": str(t.id), "subject": t.subject, "status": t.status,
            "category": t.category, "created_at": t.created_at.isoformat()}


@router.get("/tickets/{ticket_id}/messages")
async def get_ticket_messages(ticket_id: uuid.UUID,
                              user: CurrentUser = Depends(get_current_user),
                              db: AsyncSession = Depends(get_db)):
    await _my_ticket(ticket_id, user, db)  # 404s if not caller's org
    rows = (
        await db.execute(
            select(SupportMessage).where(SupportMessage.ticket_id == ticket_id)
            .order_by(SupportMessage.created_at.asc())
        )
    ).scalars().all()
    return [{"sender": m.sender, "body": m.body, "created_at": m.created_at.isoformat()}
            for m in rows]


# ── Clinic-user actions: reply to own ticket, rate a resolved ticket ─────────


class ReplyBody(BaseModel):
    body: str = Field(..., min_length=1, max_length=8000)


class CsatBody(BaseModel):
    score: int = Field(..., ge=1, le=5)
    comment: str | None = Field(None, max_length=2000)


@router.post("/tickets/{ticket_id}/messages")
async def add_user_reply(ticket_id: uuid.UUID, body: ReplyBody,
                         user: CurrentUser = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    t = await _my_ticket(ticket_id, user, db)  # 404 if not caller's org
    db.add(SupportMessage(ticket_id=t.id, sender="user",
                          sender_user_id=user.user_id, body=body.body))
    # A user reply always wants a human now — reopen unless already active.
    if t.status in ("ai_resolved", "resolved", "closed", "pending"):
        t.status = "open"
    await db.commit()
    # No team email on replies (Vinay 2026-07-12, Resend quota) — the dashboard
    # shows the reopened ticket; the SLA sweep still catches anything ignored.
    logger.info("support_user_reply", ticket_id=str(t.id))
    return {"ok": True, "status": t.status}


@router.post("/tickets/{ticket_id}/csat")
async def rate_ticket(ticket_id: uuid.UUID, body: CsatBody,
                      user: CurrentUser = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)):
    t = await _my_ticket(ticket_id, user, db)
    if t.status not in ("resolved", "closed"):
        raise HTTPException(status_code=409, detail="Only a resolved ticket can be rated")
    t.csat_score = body.score
    t.csat_comment = body.comment
    await db.commit()
    logger.info("support_csat", ticket_id=str(t.id), score=body.score)
    return {"ok": True}


# ── Public / authed contact + demo form → a ticket (public lead = org_id NULL) ─


class ContactBody(BaseModel):
    # Email optional ONLY for demo leads (phone-first); enforced below.
    email: str | None = Field(None, max_length=255)
    name: str | None = Field(None, max_length=255)
    phone: str | None = Field(None, max_length=20)
    subject: str = Field(..., min_length=1, max_length=200)
    body: str = Field(..., min_length=1, max_length=8000)
    category: str = Field("other", max_length=32)


_CONTACT_CATEGORIES = {"billing", "technical", "onboarding", "feature_request",
                       "sales_demo", "other"}


@router.post("/contact", dependencies=[Depends(default_limit)])
async def contact(body: ContactBody, request: Request, db: AsyncSession = Depends(get_db)):
    user = await optional_current_user(request)
    await _guard_anonymous(request, user)  # Turnstile for anonymous only
    category = body.category if body.category in _CONTACT_CATEGORIES else "other"
    is_demo = category == "sales_demo"
    phone_digits = "".join(c for c in (body.phone or "") if c.isdigit())[-10:]
    if is_demo:
        # A demo lead is a callback: 10-digit Indian mobile required.
        if len(phone_digits) != 10:
            raise HTTPException(status_code=422, detail="A 10-digit phone number is required to book a demo")
    elif not user and not (body.email and len(body.email) >= 3):
        raise HTTPException(status_code=422, detail="Email is required")
    ticket = SupportTicket(
        org_id=(user.org_id if user else None),
        email=(user.email if user else (body.email or "")),
        name=body.name,
        phone=phone_digits or None,
        subject=body.subject,
        category=category,
        status="open",
        # Leads jump the queue: a hot clinic owner cools off fast.
        priority="high" if is_demo else "normal",
        source="in_app" if (user and user.org_id) else "public_form",
        sla_due_at=_sla_due("high" if is_demo else "normal"),
    )
    db.add(ticket)
    await db.flush()
    db.add(SupportMessage(ticket_id=ticket.id, sender="user", body=body.body))
    await db.commit()
    await support_email.notify_new_ticket(ticket.id, ticket.subject, ticket.email)  # RULE 8
    logger.info("support_contact", ticket_id=str(ticket.id),
                org_id=str(ticket.org_id) if ticket.org_id else None)
    return {"ok": True, "ticket_id": str(ticket.id)}


# ── Support-staff dashboard (role 'support' or 'super_admin'; PII-locked) ──────


def _admin_row(t: SupportTicket) -> dict:
    return {
        "id": str(t.id), "org_id": str(t.org_id) if t.org_id else None,
        "email": t.email, "name": t.name, "phone": t.phone, "subject": t.subject,
        "category": t.category, "status": t.status, "priority": t.priority,
        "source": t.source,
        "sla_due_at": t.sla_due_at.isoformat() if t.sla_due_at else None,
        "csat_score": t.csat_score,
        "created_at": t.created_at.isoformat(),
    }


@router.get("/admin/tickets")
async def admin_list_tickets(
    status: str | None = None, priority: str | None = None,
    category: str | None = None, overdue: bool = False, leads: bool = False,
    _staff: CurrentUser = Depends(require_support_staff),
    db: AsyncSession = Depends(get_db),
):
    q = select(SupportTicket)
    if status:
        q = q.where(SupportTicket.status == status)
    else:
        q = q.where(SupportTicket.status != "ai_resolved")  # default: needs-human
    if priority:
        q = q.where(SupportTicket.priority == priority)
    # Leads (demo requests) live in their own tab: leads=true shows ONLY them;
    # the ordinary inbox never mixes them in (Vinay 2026-07-12: "new clients
    # should be handled differently").
    if leads:
        q = q.where(SupportTicket.category == "sales_demo")
    elif category:
        q = q.where(SupportTicket.category == category)
    else:
        q = q.where(SupportTicket.category != "sales_demo")
    if overdue:
        q = q.where(
            SupportTicket.sla_due_at < datetime.now(timezone.utc),
            SupportTicket.first_responded_at.is_(None),
        )
    q = q.order_by(SupportTicket.created_at.desc()).limit(500)
    rows = (await db.execute(q)).scalars().all()
    return [_admin_row(t) for t in rows]


async def _any_ticket(ticket_id: uuid.UUID, db: AsyncSession) -> SupportTicket:
    t = (
        await db.execute(select(SupportTicket).where(SupportTicket.id == ticket_id))
    ).scalar_one_or_none()
    if t is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return t


@router.get("/admin/tickets/{ticket_id}")
async def admin_get_ticket(ticket_id: uuid.UUID,
                           _staff: CurrentUser = Depends(require_support_staff),
                           db: AsyncSession = Depends(get_db)):
    return _admin_row(await _any_ticket(ticket_id, db))


@router.get("/admin/tickets/{ticket_id}/messages")
async def admin_ticket_messages(ticket_id: uuid.UUID,
                                _staff: CurrentUser = Depends(require_support_staff),
                                db: AsyncSession = Depends(get_db)):
    await _any_ticket(ticket_id, db)
    rows = (
        await db.execute(
            select(SupportMessage).where(SupportMessage.ticket_id == ticket_id)
            .order_by(SupportMessage.created_at.asc())
        )
    ).scalars().all()
    return [{"sender": m.sender, "body": m.body, "created_at": m.created_at.isoformat()}
            for m in rows]


@router.post("/admin/tickets/{ticket_id}/reply")
async def admin_reply(ticket_id: uuid.UUID, body: ReplyBody,
                      staff: CurrentUser = Depends(require_support_staff),
                      db: AsyncSession = Depends(get_db)):
    t = await _any_ticket(ticket_id, db)
    db.add(SupportMessage(ticket_id=t.id, sender="staff",
                          sender_user_id=staff.user_id, body=body.body))
    if t.first_responded_at is None:
        t.first_responded_at = datetime.now(timezone.utc)
    if t.status in ("open", "ai_resolved"):
        t.status = "pending"  # awaiting the user's next reply
    await db.commit()
    await support_email.notify_staff_reply(t.email, t.subject)  # RULE 8
    logger.info("support_staff_reply", ticket_id=str(t.id), staff_id=staff.user_id)
    return {"ok": True, "status": t.status}


class StatusPatch(BaseModel):
    status: str | None = None
    priority: str | None = None


_STATUSES = {"ai_resolved", "open", "pending", "resolved", "closed"}
_PRIORITIES = {"low", "normal", "high", "urgent"}


@router.patch("/admin/tickets/{ticket_id}")
async def admin_patch_ticket(ticket_id: uuid.UUID, body: StatusPatch,
                             staff: CurrentUser = Depends(require_support_staff),
                             db: AsyncSession = Depends(get_db)):
    t = await _any_ticket(ticket_id, db)
    notify_resolved = False
    if body.status is not None:
        if body.status not in _STATUSES:
            raise HTTPException(status_code=422, detail="bad status")
        if body.status == "resolved" and t.status != "resolved":
            t.resolved_at = datetime.now(timezone.utc)
            notify_resolved = True
        t.status = body.status
    if body.priority is not None:
        if body.priority not in _PRIORITIES:
            raise HTTPException(status_code=422, detail="bad priority")
        t.priority = body.priority
    await db.commit()
    if notify_resolved:
        await support_email.notify_resolved(t.email, t.subject)  # RULE 8
    logger.info("support_ticket_patched", ticket_id=str(t.id), status=t.status,
                priority=t.priority)
    return _admin_row(t)


@router.get("/admin/macros")
async def admin_macros(_staff: CurrentUser = Depends(require_support_staff)):
    return support_macros.MACROS


# ── Support-STAFF provisioning (super_admin only — staff can't mint staff) ─────


class StaffCreate(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    name: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=8, max_length=128)


@router.get("/admin/staff")
async def list_staff(_admin: CurrentUser = Depends(require_support_admin),
                     db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(select(User).where(User.role == "support")
                         .order_by(User.created_at.desc()))
    ).scalars().all()
    return [{"id": str(u.id), "email": u.email, "name": u.name} for u in rows]


@router.post("/admin/staff")
async def create_staff(body: StaffCreate, _admin: CurrentUser = Depends(require_support_admin),
                       db: AsyncSession = Depends(get_db)):
    from backend.routers.auth import _hash_password

    email = body.email.strip().lower()
    exists = (
        await db.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=409, detail="A user with that email already exists")
    user = User(
        org_id=None,  # platform-level, belongs to Vachanam not a clinic
        email=email,
        name=body.name.strip(),
        role="support",
        is_admin=False,  # NOT a super_admin — support inbox only, PII-locked
        branch_ids=[],
        password_hash=_hash_password(body.password),
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="A user with that email already exists")
    logger.info("support_staff_created", staff_id=str(user.id))
    return {"id": str(user.id), "email": user.email, "name": user.name}


@router.delete("/admin/staff/{staff_id}")
async def delete_staff(staff_id: uuid.UUID, _admin: CurrentUser = Depends(require_support_admin),
                       db: AsyncSession = Depends(get_db)):
    u = (
        await db.execute(select(User).where(User.id == staff_id, User.role == "support"))
    ).scalar_one_or_none()
    if u is None:
        raise HTTPException(status_code=404, detail="Support staff not found")
    await db.delete(u)
    await db.commit()
    logger.info("support_staff_deleted", staff_id=str(staff_id))
    return {"ok": True}

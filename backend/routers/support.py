"""Support: KB read + grounded chatbot that auto-logs a ticket per chat.

RULE 1: bot has no clinic-data access; authed tickets carry the caller's org,
and ticket reads are WHERE org_id scoped.
RULE 8: bot failure returns a safe refusal, never a 500.
RULE 9: log ticket/message IDs, never bodies.
"""
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.middleware.auth_middleware import (
    CurrentUser,
    get_current_user,
    optional_current_user,
)
from backend.middleware.rate_limit import default_limit
from backend.models.schema import SupportMessage, SupportTicket
from backend.services import support_bot, support_kb
from backend.services.turnstile import require_turnstile

logger = structlog.get_logger()
router = APIRouter()


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


@router.post("/chat", dependencies=[Depends(default_limit), Depends(require_turnstile)])
async def chat(body: ChatRequest, request: Request, db: AsyncSession = Depends(get_db)):
    user = await optional_current_user(request)
    audience = "clinic" if user and user.org_id else "public"
    result = await support_bot.answer(
        body.question, [t.model_dump() for t in body.history], audience,
        plan=None,  # RULE 1: bot stays clinic-data-free in Phase 1
    )

    # One ticket per chat SESSION: reuse the caller's ticket if supplied, else open one.
    ticket = None
    caller_org = str((user.org_id if user else None) or "")
    if body.ticket_id:
        ticket = (
            await db.execute(select(SupportTicket).where(SupportTicket.id == body.ticket_id))
        ).scalar_one_or_none()
        if ticket and str(ticket.org_id or "") != caller_org:
            ticket = None  # not this caller's ticket → open a fresh one
    if ticket is None:
        ticket = SupportTicket(
            org_id=(user.org_id if user else None),
            email=(user.email if user else "anonymous@vachanam.in"),
            subject=body.question[:200],
            category="other",
            status="ai_resolved" if result["answered"] else "open",
            priority="normal",
            source="in_app" if (user and user.org_id) else "public_chat",
        )
        db.add(ticket)
        await db.flush()
    elif not result["answered"] and ticket.status == "ai_resolved":
        ticket.status = "open"  # a later unanswered turn re-opens for a human

    db.add_all([
        SupportMessage(ticket_id=ticket.id, sender="user", body=body.question),
        SupportMessage(ticket_id=ticket.id, sender="bot", body=result["answer"]),
    ])
    await db.commit()
    logger.info(
        "support_chat", ticket_id=str(ticket.id), answered=result["answered"],
        org_id=str(ticket.org_id) if ticket.org_id else None,
    )
    return {"answer": result["answer"], "answered": result["answered"],
            "ticket_id": str(ticket.id)}

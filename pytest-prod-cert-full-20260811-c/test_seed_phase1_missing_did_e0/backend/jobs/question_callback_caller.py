"""Dispatch outbound "here is the answer to your question" callbacks.

A caller asked something the AI could not answer → log_clinic_question stored it
→ the doctor answered it on the dashboard (branches.answer_question) → this job
calls the caller back and the agent speaks the answer (Vinay 2026-08-02: "either
way call the person and answer the question").

Mirrors next_visit_followup_caller deliberately: same dispatch + join
verification, same courtesy calling window, same dispatch-then-mutate ordering
so a crash mid-dispatch can never mark a callback delivered that never rang.
RULE 9: metadata carries the question + the clinic's own answer only — never
medical notes; logs stay on last-4.
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import select

from backend.database import AsyncSessionLocal
from backend.models.schema import Branch, ClinicQuestion, Patient
from backend.services.telephony import branch_outbound_trunk_id

logger = structlog.get_logger()
IST = ZoneInfo("Asia/Kolkata")
# DPDP courtesy window, same as the treatment follow-up booking nudge.
CALL_START_H, CALL_END_H = 9, 20
AGENT_NAME = "vachanam-agent"
MAX_ATTEMPTS = 3


def compose_message(question: str, answer: str) -> str:
    """The whole spoken opening, in English. The agent translates it into the
    call's language at ring time (_localize_message) — which is why this needs
    no per-language copy of its own."""
    q = (question or "").strip().rstrip("?")
    return (
        f"You had asked us about {q}. I checked with the clinic, "
        f"and here is the answer. {(answer or '').strip()}"
    )


async def _dispatch(q: ClinicQuestion, branch: Branch, patient_name: str) -> bool:
    """Create the dispatch AND verify a worker actually joined (#423). Returns
    False when nobody picked it up — the row stays queued for the next tick."""
    try:
        outbound_trunk_id = branch_outbound_trunk_id(branch)
    except RuntimeError:
        logger.error(
            "question_callback_blocked_missing_branch_trunk",
            branch_id=str(branch.id),
            question_id=str(q.id),
        )
        return False

    # Same collision guard as the other three dialers (Vinay 2026-08-08).
    from backend.services.outbound_guard import (
        claim_outbound_call,
        release_outbound_call,
    )

    if not await claim_outbound_call(q.caller_phone, "question_answer"):
        return False
    try:
        from livekit import api as lk_api

        lkapi = lk_api.LiveKitAPI()
        try:
            meta = {
                "call_type": "question_answer",
                "branch_id": str(branch.id),
                "outbound_trunk_id": outbound_trunk_id,
                "phone_number": q.caller_phone,
                "patient_name": patient_name or "",
                "message": compose_message(q.question, q.answer or ""),
                "question_id": str(q.id),
            }
            room = f"qanswer-{uuid.uuid4().hex[:10]}"
            await lkapi.agent_dispatch.create_dispatch(
                lk_api.CreateAgentDispatchRequest(
                    agent_name=AGENT_NAME, room=room, metadata=json.dumps(meta)
                )
            )
            from backend.services.dispatch_verify import verify_or_cleanup

            if not await verify_or_cleanup(lkapi, room, f"question:{q.id}"):
                await release_outbound_call(q.caller_phone)
                return False
            logger.info(
                "question_callback_dispatched",
                question_id=str(q.id),
                room=room,
                phone_last4=(q.caller_phone or "")[-4:],
            )
            return True
        finally:
            await lkapi.aclose()
    except Exception as e:  # noqa: BLE001 — RULE 8
        logger.error("question_callback_dispatch_failed", question_id=str(q.id),
                     error=str(e)[:160])
        await release_outbound_call(q.caller_phone)
        return False


async def run_question_callbacks(now: datetime | None = None) -> int:
    from backend.jobs import wake_gate

    now_ist = (now or datetime.now(IST)).astimezone(IST)
    if not (CALL_START_H <= now_ist.hour < CALL_END_H):
        return 0
    # #299: nothing queued ⇒ answer from Redis, leave Postgres asleep. The
    # answer endpoint clears this key, so a fresh answer is dialed next tick.
    if not await wake_gate.should_run_scheduled("question_callbacks"):
        return 0
    dispatched = 0
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(ClinicQuestion).where(ClinicQuestion.status == "answered")
            )
        ).scalars().all()
        for q in rows:
            if not q.caller_phone:
                q.status = "unreachable"
                await db.commit()   # COMMIT PER ROW — one bad row can't roll back the batch
                continue
            branch = (
                await db.execute(select(Branch).where(Branch.id == q.branch_id))
            ).scalar_one_or_none()
            if branch is None:
                q.status = "unreachable"
                await db.commit()
                continue
            name = ""
            if q.patient_id:
                name = (
                    await db.execute(select(Patient.name).where(Patient.id == q.patient_id))
                ).scalar_one_or_none() or ""
            # DISPATCH-THEN-MUTATE (FIXLOG #160): never flip status before the
            # phone actually rings, or a crash strands the callback forever.
            q.call_attempts = (q.call_attempts or 0) + 1
            if await _dispatch(q, branch, name):
                q.status = "called"
                dispatched += 1
            elif q.call_attempts >= MAX_ATTEMPTS:
                q.status = "unreachable"
            # else: stays 'answered' → retried on the next tick
            await db.commit()

        still_queued = (
            await db.execute(
                select(ClinicQuestion.id).where(ClinicQuestion.status == "answered").limit(1)
            )
        ).first()
        # Real clock, not the injected `now`: this is "there is work, keep
        # ticking", so it must not park the gate in the future.
        await wake_gate.set_next_at(
            "question_callbacks", time.time() if still_queued else None
        )
    return dispatched

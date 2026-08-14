"""Deliver a doctor's answer back down the channel the patient used.

Vinay 2026-08-04: "questions asked in whatsapp should get whatsapp reply after
getting confirmation from clinic. not call. because, those people whatsapp
clinic because they don't want to talk."

Before this, every answered ClinicQuestion was handed to the callback job and
the patient's phone rang — including for someone who had deliberately typed
rather than call. The answer was right and the delivery was wrong.

THE 24-HOUR WINDOW is the one real constraint. Meta only permits free-form
text within 24 hours of the patient's last message; after that only an
approved template may be sent, and no clinic has registered a
"here-is-your-answer" template (their approved set is booking-shaped:
confirm / reschedule / cancel / feedback). So this tries the free-form reply
and reports whether it landed. A failure is not swallowed — it returns False,
the question stays `answered`, and the existing callback job dials as it always
did. The patient always gets their answer; WhatsApp is simply preferred.

RULE 1: the branch is loaded and matched before anything is sent.
RULE 9: logs carry phone[-4:] and the question id — never the question or the
answer text.
"""
from __future__ import annotations

import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.schema import Branch, Organization
from backend.services import wa_service, wa_session

logger = structlog.get_logger()


def compose(question: str, answer: str) -> str:
    """What the patient reads.

    Their own question is quoted back because the doctor may answer hours
    later, by which time "Yes, we do" alone is meaningless.
    """
    asked = " ".join((question or "").split())
    if len(asked) > 160:
        asked = asked[:157].rstrip() + "…"
    body = " ".join((answer or "").split())
    if asked:
        return f'You asked: "{asked}"\n\n{body}'
    return body


async def reply(
    db: AsyncSession, branch_id: uuid.UUID, question, answer: str
) -> bool:
    """Send the answer over WhatsApp. True only if it actually went.

    False means the caller should leave the question queued for the phone
    callback — never that the patient goes without an answer.
    """
    to = getattr(question, "caller_phone", None)
    if not to:
        return False
    try:
        row = (
            await db.execute(
                select(Branch, Organization.plan)
                .join(Organization, Organization.id == Branch.org_id)
                .where(Branch.id == branch_id)  # RULE 1
            )
        ).first()
        if row is None:
            return False
        branch, plan = row
        if not wa_service.wa_enabled(branch, plan):
            return False

        text = compose(getattr(question, "question", ""), answer)
        sent = await wa_service.send_text(branch, to, text, plan=plan)
        if sent:
            # Record it in the thread so the assistant's next turn knows the
            # doctor has already answered, and the clinic sees it in Chats.
            try:
                await wa_session.append(db, branch.id, to, "bot", text)
            except Exception as e:  # noqa: BLE001 — transcript is not the point
                logger.debug("wa_answer_session_append_failed", error=str(e)[:120])
        logger.info(
            "wa_question_answer_delivered" if sent else "wa_question_answer_undelivered",
            branch_id=str(branch_id),
            question_id=str(getattr(question, "id", ""))[:8],
            phone_last4=(to or "")[-4:],
        )
        return bool(sent)
    except Exception as e:  # noqa: BLE001 — fall back to the phone callback
        logger.warning(
            "wa_question_answer_failed", branch_id=str(branch_id),
            error=str(e)[:200],
        )
        return False

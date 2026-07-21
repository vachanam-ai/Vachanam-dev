"""WhatsApp Cloud API sends (spec 2026-07-13, plan T3).

One Vachanam-level system-user token (settings.meta_access_token); the SENDER
identity is per-branch — branch.wa_phone_number_id, the clinic's own
Coexistence-linked number. RULE 4: a send failure NEVER raises into a booking
path — every public function returns bool and logs. RULE 9: logs carry
to_last4 + template name + branch_id, never body text.

No creds / no linked number / wrong plan → structured no-op (False), so the
whole feature is inert until Vinay finishes the Meta runbook (Phase A) and a
branch is linked (Phase B).
"""
from __future__ import annotations

import httpx
import structlog
from tenacity import (
    retry, retry_if_exception_type, stop_after_attempt, wait_exponential,
)

from backend.config import settings
from backend.services.billing_math import WHATSAPP_PLANS

logger = structlog.get_logger()

_GRAPH = "https://graph.facebook.com/v21.0"


def wa_enabled(branch, plan: str | None) -> bool:
    """True when this branch can send WhatsApp right now: platform creds set,
    branch number linked, org plan gated in (Clinic+Multi — Vinay)."""
    if not settings.meta_access_token:
        logger.debug("wa_skipped_unconfigured", reason="no_access_token")
        return False
    if not getattr(branch, "wa_phone_number_id", None):
        logger.debug(
            "wa_skipped_unconfigured", reason="branch_not_linked",
            branch_id=str(getattr(branch, "id", None)),
        )
        return False
    if (plan or "") not in WHATSAPP_PLANS:
        logger.info(
            "wa_skipped_plan", plan=plan,
            branch_id=str(getattr(branch, "id", None)),
        )
        return False
    return True


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
    reraise=True,
)
async def _post(phone_number_id: str, payload: dict) -> None:
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(
            f"{_GRAPH}/{phone_number_id}/messages",
            headers={"Authorization": f"Bearer {settings.meta_access_token}"},
            json=payload,
        )
        r.raise_for_status()


async def _send(branch, plan: str | None, to: str, payload: dict, kind: str, detail: str) -> bool:
    """Shared guarded send. RULE 4: catches everything terminal."""
    if not wa_enabled(branch, plan):
        return False
    try:
        await _post(branch.wa_phone_number_id, payload)
        logger.info(
            "wa_sent", kind=kind, detail=detail,
            to_last4=to[-4:] if to else None, branch_id=str(branch.id),
        )
        return True
    except Exception as e:  # noqa: BLE001 — notification channel, never raises out
        logger.warning(
            "wa_send_failed", kind=kind, detail=detail,
            to_last4=to[-4:] if to else None, branch_id=str(branch.id),
            error=str(e)[:200],
        )
        return False


async def send_template(
    branch,
    to: str,
    template: str,
    lang: str,
    body_params: list[str],
    buttons: list[dict] | None = None,
    plan: str | None = None,
) -> bool:
    """Business-initiated utility template. buttons = quick replies:
    [{"id": "rs:<token_id>", "title": "Reschedule"}, ...] — ids follow the
    T4 grammar (rs:/cx:/rate:/slot:) that the T5 webhook dispatches on."""
    components: list[dict] = []
    if body_params:
        components.append({
            "type": "body",
            "parameters": [{"type": "text", "text": p} for p in body_params],
        })
    for i, btn in enumerate(buttons or []):
        components.append({
            "type": "button",
            "sub_type": "quick_reply",
            "index": str(i),
            "parameters": [{"type": "payload", "payload": btn["id"]}],
        })
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": template,
            "language": {"code": lang},
            "components": components,
        },
    }
    return await _send(branch, plan, to, payload, "template", template)


async def send_text(branch, to: str, text: str, plan: str | None = None) -> bool:
    """Free-form session reply — only valid inside Meta's 24h service window,
    which every caller of this function is by construction (we only reply)."""
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text},
    }
    return await _send(branch, plan, to, payload, "text", "session_reply")


async def send_interactive(
    branch, to: str, interactive: dict, plan: str | None = None
) -> bool:
    """Interactive session message (button/list picker) — same 24h-window
    contract as send_text."""
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": interactive,
    }
    return await _send(
        branch, plan, to, payload, "interactive", interactive.get("type", "?")
    )

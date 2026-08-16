"""WhatsApp Cloud API sends (spec 2026-07-13, plan T3; per-branch token WA
MVP1 Task 2).

The SENDER identity is per-branch — branch.wa_phone_number_id, the clinic's
own number. The bearer TOKEN is also resolved per branch via `token_for`:
a clinic that has connected its own WABA (Task 1's `wa_token_enc`, Fernet
encrypted) sends with ITS token; a branch with none falls back to the
Vachanam-level platform token (settings.meta_access_token) — "bridge mode".

RULE 1: a clinic token that will not decrypt fails CLOSED — `token_for`
returns None rather than ever falling back to the platform token, because
that fallback would send THIS clinic's message from Vachanam's own WhatsApp
account (cross-tenant send). RULE 4: a send failure NEVER raises into a
booking path — every public function returns bool and logs. RULE 9: logs
carry to_last4 + template name + branch_id, never body text, never any part
of a token.

No creds / no linked number / wrong plan / no resolvable token → structured
no-op (False), so the whole feature is inert until Vinay finishes the Meta
runbook (Phase A) and a branch is linked (Phase B).
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx
import structlog
from tenacity import (
    retry, retry_if_exception_type, stop_after_attempt, wait_exponential,
)

from backend.config import settings
from backend.services.billing_math import whatsapp_enabled
from backend.services.crypto import decrypt_secret
from backend.services.meta_graph import url as graph_url
from backend.services.wa_lifecycle import is_connected

logger = structlog.get_logger()

def token_for(branch) -> str | None:
    """The Meta bearer token this branch sends with.

    A clinic token (`branch.wa_token_enc`, Fernet-encrypted) that will not
    decrypt fails CLOSED: returning None here — never falling back to the
    platform token — because that fallback would send this clinic's message
    from Vachanam's own WhatsApp account (RULE 1, cross-tenant send). Only a
    branch with NO token at all (wa_token_enc is None/empty — bridge mode)
    may use the platform token.
    """
    enc = getattr(branch, "wa_token_enc", None)
    if enc:
        expiry = (getattr(branch, "wa_onboarding", None) or {}).get("token_expires_at")
        if expiry:
            try:
                if datetime.fromisoformat(expiry) <= datetime.now(timezone.utc):
                    logger.warning("wa_token_expired", branch_id=str(getattr(branch, "id", None)))
                    return None
            except (TypeError, ValueError):
                logger.warning("wa_token_expiry_invalid", branch_id=str(getattr(branch, "id", None)))
                return None
        try:
            return decrypt_secret(enc)
        except Exception as e:  # noqa: BLE001 — fail closed, never leak the token
            logger.error(
                "wa_token_undecryptable",
                branch_id=str(getattr(branch, "id", None)),
                error=str(e)[:120],
            )
            return None
    # Official Embedded Signup branches must always use their own business
    # integration token. The platform token remains only for pre-v4 controlled
    # test-number records that have no onboarding state.
    if getattr(branch, "wa_onboarding", None):
        return None
    return settings.meta_access_token or None


def wa_enabled(branch, plan: str | None) -> bool:
    """True when this branch can send WhatsApp right now: a usable token,
    branch number linked, org plan gated in (clinic/multi/wa — Vinay).

    The token check is `token_for(branch)`, NOT the platform token: under the
    clinic-owned WABA model a branch sends with its OWN credential, and the
    platform token may legitimately be unset. Gating on it would report every
    clinic-owned branch as disabled.
    """
    if not is_connected(branch):
        logger.debug(
            "wa_skipped_unconfigured",
            reason="branch_disconnected",
            branch_id=str(getattr(branch, "id", None)),
        )
        return False
    if not token_for(branch):
        logger.debug("wa_skipped_unconfigured", reason="no_access_token")
        return False
    # The per-branch add-on lets a voice clinic buy WhatsApp independently.
    # Clinic. getattr defaults to False so a branch object loaded before the
    # column existed (or a bare test stub) can never accidentally grant a paid
    # feature. Flag lives on the BRANCH because WhatsApp is provisioned per
    # number — each branch has its own WABA and its own Meta billing.
    addon = bool(getattr(branch, "whatsapp_addon", False))
    if not whatsapp_enabled(plan or "", addon):
        logger.info(
            "wa_skipped_plan", plan=plan, addon=addon,
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
async def _post(phone_number_id: str, payload: dict, token: str) -> None:
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(
            graph_url(f"{phone_number_id}/messages"),
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )
        # getattr: test doubles stub only what they need. A stub without
        # is_error falls through to raise_for_status() below, which is the
        # behaviour that existed before this enrichment.
        if getattr(r, "is_error", False):
            # raise_for_status() keeps only the status line, so a 400 logged as
            # "Client error '400 Bad Request'" and nothing else — useless, and it
            # cost real debugging time (2026-08-03). Meta ALWAYS says why in the
            # body (error.code / error.message / error_data.details); surface it.
            # RULE 9: Meta's error text describes OUR request, not patient
            # content, and the body never echoes the message we sent.
            detail = ""
            try:
                err = (r.json() or {}).get("error") or {}
                detail = (
                    f" code={err.get('code')} subcode={err.get('error_subcode')} "
                    f"msg={str(err.get('message'))[:200]} "
                    f"details={str((err.get('error_data') or {}).get('details'))[:200]}"
                )
            except Exception:  # noqa: BLE001 — non-JSON body
                detail = f" body={r.text[:200]}"
            raise httpx.HTTPStatusError(
                f"{r.status_code} from Meta:{detail}", request=r.request, response=r
            )
        r.raise_for_status()


async def _send(branch, plan: str | None, to: str, payload: dict, kind: str, detail: str) -> bool:
    """Shared guarded send. RULE 4: catches everything terminal.

    Token resolution is per-branch (RULE 1 — see `token_for`); a branch
    that resolves to no usable token is a structured no-op, never a
    fallback to another identity.
    """
    if not wa_enabled(branch, plan):
        return False
    token = token_for(branch)
    if not token:
        logger.warning(
            "wa_send_no_token", kind=kind, detail=detail,
            to_last4=to[-4:] if to else None, branch_id=str(getattr(branch, "id", None)),
        )
        return False
    try:
        await _post(branch.wa_phone_number_id, payload, token)
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
    which every caller of this function is by construction (we only reply).

    Every free-text reply in the product goes out through here, which is why
    the English-letters rule (Vinay 2026-08-07) is enforced at this line and
    not at each of the fourteen call sites. The prompt asks the model for
    Latin script; a prompt is a request, and this is the guarantee.
    """
    from agent.i18n.transliterate import to_latin

    text = await to_latin(text)
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

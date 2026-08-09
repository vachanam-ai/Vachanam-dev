"""WhatsApp Embedded Signup — Tech Provider connect flow (WA MVP1 Task 9).

Replaces `scripts/wa_link_branch.py` hand-linking for clinics that go through
Meta's Embedded Signup JS flow: the clinic connects its OWN WhatsApp Business
Account (WABA) instead of Vinay pasting a phone_number_id.

Flow (frontend does the Meta JS SDK dance, then posts three values here):
  1. `code`             — one-time authorization code from FB.login's callback
  2. `waba_id`           the WABA id Meta's embedded-signup session_info event
  3. `phone_number_id`    delivers directly to the frontend

Server side:
  1. Exchange `code` for a business access token (GET /oauth/access_token).
  2. Subscribe our app to that WABA's webhooks (POST /{waba_id}/subscribed_apps)
     — MANDATORY. Without this no inbound message or status webhook ever
     reaches us, so a subscribe failure aborts the whole connect (raises).
  3. Register the phone number for Cloud API (POST /{phone_number_id}/register)
     — best-effort. A coexistence number already live on the WhatsApp Business
     app can reject re-registration; that is not a connect failure, only the
     subscribe step above is load-bearing.
  4. Fetch the verified display name (GET /{phone_number_id}?fields=verified_name)
     for the Setup tab — cosmetic, never blocks connect on failure.

RULE 1: `Branch.wa_waba_id` is UNIQUE — the router checks for a clash BEFORE
calling Meta at all, and the same uniqueness is enforced at the DB layer as a
backstop (IntegrityError -> 409) against a concurrent double-connect race.

RULE 9: the authorization code and the business token are NEVER logged, not
even truncated — every log line here carries branch_id / waba_id / status
only. `encrypt_secret` (Fernet, backend/services/crypto.py) is the only place
the plaintext token exists outside the Graph response itself.

RULE 5: every external Graph call retries transient failures 3x with
exponential backoff (mirrors backend/services/wa_service.py's `_post`).
"""
from __future__ import annotations

import httpx
import structlog
from tenacity import (
    retry, retry_if_exception_type, stop_after_attempt, wait_exponential,
)

from backend.config import settings
from backend.services.crypto import encrypt_secret

logger = structlog.get_logger()

_GRAPH = "https://graph.facebook.com/v21.0"

_retry_graph = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
    reraise=True,
)


class WaConnectError(Exception):
    """Carries the HTTP status the route should return and a message safe to
    show the clinic owner verbatim — never a raw Graph error body."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


@_retry_graph
async def _exchange_code(code: str) -> str:
    """One-time authorization code -> long-lived business access token.

    RULE 9: `code` and the returned token are never logged, not even a
    fragment — only whether the exchange succeeded.
    """
    if not settings.meta_app_id or not settings.meta_app_secret:
        raise WaConnectError(
            500, "WhatsApp connect is not configured on this server yet."
        )
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(
            f"{_GRAPH}/oauth/access_token",
            params={
                "client_id": settings.meta_app_id,
                "client_secret": settings.meta_app_secret,
                "code": code,
            },
        )
        r.raise_for_status()
        data = r.json()
    token = data.get("access_token")
    if not token:
        raise WaConnectError(502, "WhatsApp did not return a usable access token.")
    return token


@_retry_graph
async def _subscribe_app(waba_id: str, token: str) -> None:
    """Subscribe our app to this WABA's webhooks. MANDATORY — without this no
    inbound message, status update, or template review event ever reaches us."""
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(
            f"{_GRAPH}/{waba_id}/subscribed_apps",
            headers={"Authorization": f"Bearer {token}"},
        )
        r.raise_for_status()


async def _register_phone(phone_number_id: str, token: str) -> bool:
    """Best-effort Cloud API registration. A coexistence number already
    running on the WhatsApp Business app can legitimately reject this
    (already registered) — that must never fail the connect; only the
    subscribe step above is load-bearing. Returns whether it succeeded so the
    caller can surface it as an informational flag, never an error."""
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(
                f"{_GRAPH}/{phone_number_id}/register",
                headers={"Authorization": f"Bearer {token}"},
                json={"messaging_product": "whatsapp"},
            )
        if r.status_code >= 300:
            logger.info("wa_register_skipped", status=r.status_code)
            return False
        return True
    except httpx.TransportError as e:
        logger.info("wa_register_skipped", error=str(e)[:120])
        return False


async def _phone_verified_name(phone_number_id: str, token: str) -> str | None:
    """Cosmetic — the display name shown in the Setup tab. Never blocks
    connect: a lookup failure just leaves the name unset."""
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(
                f"{_GRAPH}/{phone_number_id}",
                params={"fields": "verified_name"},
                headers={"Authorization": f"Bearer {token}"},
            )
            r.raise_for_status()
            return r.json().get("verified_name")
    except (httpx.HTTPStatusError, httpx.TransportError) as e:
        logger.info("wa_verified_name_lookup_failed", error=str(e)[:120])
        return None


async def connect_branch(
    branch, *, code: str, waba_id: str, phone_number_id: str
) -> dict:
    """Run the full Embedded Signup connect flow and mutate `branch` in
    place (encrypted token, waba id, verified name, status, connected_at).
    Caller commits — this function never touches the DB session, so it can
    be exercised in tests without one.

    Raises `WaConnectError` on any failure of a MANDATORY step (token
    exchange, webhook subscribe). A failure of the best-effort steps
    (register, verified-name lookup) never raises — it degrades quietly and
    is reported back in the result dict.
    """
    try:
        token = await _exchange_code(code)
    except (httpx.HTTPStatusError, httpx.TransportError) as e:
        logger.warning(
            "wa_connect_token_exchange_failed",
            branch_id=str(getattr(branch, "id", None)), waba_id=waba_id,
        )
        raise WaConnectError(
            502, "Could not connect to WhatsApp — please try again."
        ) from e

    return await _finish_connect(
        branch, token=token, waba_id=waba_id, phone_number_id=phone_number_id,
    )


async def connect_branch_manual(
    branch, *, token: str, waba_id: str, phone_number_id: str
) -> dict:
    """Same connect, without Embedded Signup: the owner pastes the three
    values from Meta's own API Setup screen.

    Exists because Embedded Signup cannot run until the Meta app is published
    Live, and because a clinic on a partner-managed WABA may never see that
    popup at all. Everything after the token is identical — the subscribe is
    just as mandatory here, so a number linked this way is a real connection
    and not a half-configured branch that silently drops inbound messages.

    RULE 1: the token is REQUIRED and is stored per branch. It deliberately
    does NOT fall back to `settings.meta_access_token` — that fallback is
    bridge mode, reachable only by super_admin, and letting a clinic owner
    self-serve into it would let any clinic type Vachanam's own WABA id and
    send from the platform account.
    """
    return await _finish_connect(
        branch, token=token, waba_id=waba_id, phone_number_id=phone_number_id,
    )


async def _finish_connect(
    branch, *, token: str, waba_id: str, phone_number_id: str
) -> dict:
    """Everything a connect does once a usable token exists. Shared so the
    Embedded Signup and manual paths cannot drift into behaving differently —
    in particular so neither can skip the mandatory subscribe."""
    from datetime import datetime, timezone

    try:
        await _subscribe_app(waba_id, token)
    except (httpx.HTTPStatusError, httpx.TransportError) as e:
        logger.warning(
            "wa_connect_subscribe_failed",
            branch_id=str(getattr(branch, "id", None)), waba_id=waba_id,
        )
        raise WaConnectError(
            502,
            "Connected to WhatsApp but could not subscribe to message "
            "delivery — please check the ID and token and try again.",
        ) from e

    registered = await _register_phone(phone_number_id, token)
    verified_name = await _phone_verified_name(phone_number_id, token)

    branch.wa_waba_id = waba_id
    branch.wa_phone_number_id = phone_number_id
    branch.wa_token_enc = encrypt_secret(token)
    branch.wa_verified_name = verified_name
    branch.wa_status = "connected"
    branch.wa_connected_at = datetime.now(timezone.utc)

    logger.info(
        "wa_connect_succeeded",
        branch_id=str(getattr(branch, "id", None)), waba_id=waba_id,
        status=branch.wa_status, phone_registered=registered,
    )
    return {"registered": registered, "verified_name": verified_name}

"""Official WhatsApp Embedded Signup v4 Tech Provider onboarding.

The browser returns a short-lived code and Meta asset IDs. This module performs
every privileged step server-to-server: token exchange, asset verification,
WABA webhook subscription, conditional phone registration, and Coexistence
data-sync initiation. Secrets are encrypted before the caller commits them.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

import httpx
import structlog
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from backend.config import settings
from backend.services.crypto import decrypt_secret, encrypt_secret
from backend.services.meta_graph import url as graph_url

logger = structlog.get_logger()

FLOW_CLOUD_API = "FINISH"
FLOW_COEXISTENCE = "FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING"
SUPPORTED_FINISH_EVENTS = frozenset({FLOW_CLOUD_API, FLOW_COEXISTENCE})
PAYMENT_METHOD_URL = "https://business.facebook.com/wa/manage/home/"


def _is_transient(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    return (
        isinstance(exc, httpx.HTTPStatusError)
        and exc.response is not None
        and (exc.response.status_code == 429 or exc.response.status_code >= 500)
    )


_retry_graph = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.25, min=0.25, max=2),
    retry=retry_if_exception(_is_transient),
    reraise=True,
)


class WaConnectError(Exception):
    """HTTP status plus a clinic-safe message; never a raw Graph response."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def public_onboarding(branch) -> dict:
    """Return only lifecycle data safe for the clinic dashboard."""
    state = dict(getattr(branch, "wa_onboarding", None) or {})
    state.pop("registration_pin_enc", None)
    state.pop("business_id", None)
    state["payment_method_url"] = PAYMENT_METHOD_URL
    return state


@_retry_graph
async def _exchange_code(code: str) -> tuple[str, int | None]:
    """Spend Meta's 30-second authorization code on the server."""
    if not settings.meta_app_id or not settings.meta_app_secret:
        raise WaConnectError(500, "WhatsApp connect is not configured on this server yet.")
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(
            graph_url("oauth/access_token"),
            params={
                "client_id": settings.meta_app_id,
                "client_secret": settings.meta_app_secret,
                "code": code,
            },
        )
        response.raise_for_status()
        payload = response.json()
        token = payload.get("access_token")
        try:
            expires_in = int(payload["expires_in"]) if payload.get("expires_in") else None
        except (TypeError, ValueError):
            expires_in = None
    if not token:
        raise WaConnectError(502, "WhatsApp did not return a usable business token.")
    return token, expires_in


@_retry_graph
async def _verify_assets(waba_id: str, phone_number_id: str, token: str) -> dict:
    """Prove the browser-supplied phone belongs to the granted WABA."""
    async with httpx.AsyncClient(timeout=12) as client:
        response = await client.get(
            graph_url(f"{waba_id}/phone_numbers"),
            params={
                "fields": "id,verified_name,display_phone_number,status,quality_rating"
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        rows = response.json().get("data") or []
    match = next((row for row in rows if str(row.get("id")) == str(phone_number_id)), None)
    if match is None:
        raise WaConnectError(
            422,
            "The selected WhatsApp phone number was not granted to Vachanam. "
            "Please run the connection flow again.",
        )
    return match


async def _coexistence_status(phone_number_id: str, token: str) -> dict:
    """Best-effort diagnostics; Embedded Signup's finish event is authoritative."""
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.get(
                graph_url(phone_number_id),
                params={"fields": "is_on_biz_app,platform_type"},
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPStatusError, httpx.TransportError):
        logger.info("wa_coexistence_status_unavailable", phone_number_id=phone_number_id)
        return {}


@_retry_graph
async def _subscribe_app(waba_id: str, token: str) -> None:
    async with httpx.AsyncClient(timeout=12) as client:
        response = await client.post(
            graph_url(f"{waba_id}/subscribed_apps"),
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        if response.json().get("success") is not True:
            raise WaConnectError(502, "Meta did not confirm the webhook subscription.")


@_retry_graph
async def _register_phone(phone_number_id: str, token: str, pin: str) -> None:
    """Register a new Cloud API number with Meta's mandatory 6-digit PIN."""
    async with httpx.AsyncClient(timeout=12) as client:
        response = await client.post(
            graph_url(f"{phone_number_id}/register"),
            headers={"Authorization": f"Bearer {token}"},
            json={"messaging_product": "whatsapp", "pin": pin},
        )
        response.raise_for_status()
        if response.json().get("success") is not True:
            raise WaConnectError(502, "Meta did not confirm phone-number registration.")


@_retry_graph
async def _request_sync(phone_number_id: str, token: str, sync_type: str) -> str:
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            graph_url(f"{phone_number_id}/smb_app_data"),
            headers={"Authorization": f"Bearer {token}"},
            json={"messaging_product": "whatsapp", "sync_type": sync_type},
        )
        response.raise_for_status()
        request_id = str(response.json().get("request_id") or "")
    if not request_id:
        raise WaConnectError(502, f"Meta accepted no {sync_type} synchronization request.")
    return request_id


async def _start_coexistence_sync(
    phone_number_id: str,
    token: str,
    existing: dict | None = None,
) -> dict:
    """Start each one-shot Coexistence sync at most once per stored request ID."""
    state = dict(existing or {})
    for key, sync_type in (("contacts", "smb_app_state_sync"), ("history", "history")):
        previous = dict(state.get(key) or {})
        if previous.get("request_id") or previous.get("status") in {"complete", "declined"}:
            continue
        try:
            request_id = await _request_sync(phone_number_id, token, sync_type)
            state[key] = {"status": "requested", "request_id": request_id}
        except Exception as exc:  # keep the token so the owner can retry inside 24h
            logger.warning("wa_coexistence_sync_request_failed", sync_type=sync_type)
            state[key] = {"status": "error"}
            if isinstance(exc, WaConnectError):
                state[key]["detail"] = exc.detail
    return state


async def connect_branch(
    branch,
    *,
    code: str,
    waba_id: str,
    phone_number_id: str,
    flow_event: str,
    business_id: str | None = None,
) -> dict:
    """Complete the official Tech Provider onboarding flow and mutate branch."""
    if flow_event not in SUPPORTED_FINISH_EVENTS:
        raise WaConnectError(422, "Unsupported WhatsApp Embedded Signup completion event.")
    try:
        token, token_expires_in = await _exchange_code(code)
        phone = await _verify_assets(waba_id, phone_number_id, token)
        await _subscribe_app(waba_id, token)
    except WaConnectError:
        raise
    except (httpx.HTTPStatusError, httpx.TransportError) as exc:
        logger.warning(
            "wa_connect_graph_step_failed",
            branch_id=str(getattr(branch, "id", None)),
            waba_id=waba_id,
            status=getattr(getattr(exc, "response", None), "status_code", None),
        )
        raise WaConnectError(502, "Could not connect to WhatsApp. Please try again.") from exc

    now = datetime.now(timezone.utc)
    mode = "coexistence" if flow_event == FLOW_COEXISTENCE else "cloud_api"
    pin_enc = None
    registered = False
    sync: dict = {}

    if mode == "coexistence":
        # Meta explicitly requires registration to be skipped for a WhatsApp
        # Business app number; Embedded Signup already registered it.
        phone.update(await _coexistence_status(phone_number_id, token))
        sync = await _start_coexistence_sync(phone_number_id, token)
    else:
        if str(phone.get("status") or "").upper() == "CONNECTED":
            registered = True
        else:
            pin = f"{secrets.randbelow(1_000_000):06d}"
            try:
                await _register_phone(phone_number_id, token, pin)
            except (httpx.HTTPStatusError, httpx.TransportError) as exc:
                logger.warning(
                    "wa_phone_registration_failed",
                    branch_id=str(getattr(branch, "id", None)),
                    status=getattr(getattr(exc, "response", None), "status_code", None),
                )
                raise WaConnectError(
                    502,
                    "Meta could not register the selected phone number. "
                    "Please check the number in WhatsApp Manager and reconnect.",
                ) from exc
            registered = True
            pin_enc = encrypt_secret(pin)

    branch.wa_waba_id = waba_id
    branch.wa_phone_number_id = phone_number_id
    branch.wa_token_enc = encrypt_secret(token)
    branch.wa_verified_name = phone.get("verified_name")
    branch.wa_status = "connected"
    branch.wa_connected_at = now
    branch.wa_onboarding = {
        "embedded_signup_version": 4,
        "flow_event": flow_event,
        "mode": mode,
        "business_id": business_id,
        "token_expires_at": (
            (now + timedelta(seconds=token_expires_in)).isoformat()
            if token_expires_in else None
        ),
        "phone_registered": registered,
        "is_on_biz_app": bool(phone.get("is_on_biz_app")),
        "platform_type": phone.get("platform_type"),
        "payment_status": "required",
        "payment_confirmed_at": None,
        "registration_pin_enc": pin_enc,
        "sync_deadline": (now + timedelta(hours=24)).isoformat() if mode == "coexistence" else None,
        "sync": sync,
    }

    logger.info(
        "wa_connect_succeeded",
        branch_id=str(getattr(branch, "id", None)),
        waba_id=waba_id,
        mode=mode,
        phone_registered=registered,
    )
    return {
        "registered": registered,
        "verified_name": branch.wa_verified_name,
        "onboarding": public_onboarding(branch),
    }


async def retry_coexistence_sync(branch) -> dict:
    state = dict(getattr(branch, "wa_onboarding", None) or {})
    if state.get("mode") != "coexistence":
        raise WaConnectError(409, "This WhatsApp number does not use Coexistence sync.")
    deadline_raw = state.get("sync_deadline")
    try:
        deadline = datetime.fromisoformat(deadline_raw) if deadline_raw else None
    except ValueError:
        deadline = None
    if deadline and datetime.now(timezone.utc) >= deadline:
        raise WaConnectError(
            409,
            "Meta's 24-hour synchronization window has expired. Disconnect and reconnect WhatsApp.",
        )
    try:
        token = decrypt_secret(branch.wa_token_enc)
    except Exception as exc:
        raise WaConnectError(409, "WhatsApp authorization is no longer usable. Reconnect WhatsApp.") from exc
    state["sync"] = await _start_coexistence_sync(
        branch.wa_phone_number_id, token, state.get("sync")
    )
    branch.wa_onboarding = state
    return public_onboarding(branch)


def confirm_payment_method(branch) -> dict:
    state = dict(getattr(branch, "wa_onboarding", None) or {})
    state["payment_status"] = "confirmed"
    state["payment_confirmed_at"] = datetime.now(timezone.utc).isoformat()
    branch.wa_onboarding = state
    return public_onboarding(branch)


@_retry_graph
async def _unsubscribe_app(waba_id: str, token: str) -> bool:
    async with httpx.AsyncClient(timeout=12) as client:
        response = await client.delete(
            graph_url(f"{waba_id}/subscribed_apps"),
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        return response.json().get("success") is True


async def unsubscribe_branch(branch) -> bool:
    """Best-effort Meta unsubscribe; local revocation must still proceed."""
    if not getattr(branch, "wa_waba_id", None) or not getattr(branch, "wa_token_enc", None):
        return False
    try:
        token = decrypt_secret(branch.wa_token_enc)
        return await _unsubscribe_app(branch.wa_waba_id, token)
    except Exception as exc:  # noqa: BLE001 - never block local credential deletion
        logger.warning(
            "wa_meta_unsubscribe_failed",
            branch_id=str(getattr(branch, "id", None)),
            waba_id=getattr(branch, "wa_waba_id", None),
            status=getattr(getattr(exc, "response", None), "status_code", None),
        )
        return False

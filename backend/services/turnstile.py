"""Cloudflare Turnstile verification (bot protection on public auth endpoints).

Feature is ENV-GATED: with TURNSTILE_SECRET_KEY unset (dev, tests) every
request passes — no widget needed, no behaviour change. With the secret set
(prod), /auth/login, /auth/register, /auth/request-otp and
/auth/forgot-password require a valid X-Turnstile-Token header.

Failure policy mirrors the rate limiter (RULE 8): a Cloudflare OUTAGE fails
OPEN with a loud log — degraded bot-filtering beats a total login outage.
A REJECTED token (Cloudflare answered success=false) fails CLOSED (403).
"""
import httpx
import structlog
from fastapi import HTTPException, Request

from backend.config import settings
from backend.middleware.rate_limit import client_ip

logger = structlog.get_logger()

_SITEVERIFY = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


async def verify_turnstile(token: str | None, ip: str | None) -> bool:
    """True if the request may proceed. See module docstring for policy."""
    secret = settings.turnstile_secret_key
    if not secret:
        return True  # feature off
    if not token:
        return False  # enforced but no token supplied → bot or stale client
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.post(
                _SITEVERIFY,
                data={"secret": secret, "response": token, "remoteip": ip or ""},
            )
            ok = bool(resp.json().get("success"))
    except Exception as exc:  # noqa: BLE001 — Cloudflare outage must not kill login
        logger.error("turnstile_verify_unavailable", error=str(exc))
        return True  # fail OPEN (RULE 8)
    if not ok:
        logger.warning("turnstile_rejected", ip=ip)
    return ok


async def require_turnstile(request: Request) -> None:
    """FastAPI dependency: 403 when Turnstile is enforced and the token fails."""
    token = request.headers.get("x-turnstile-token")
    if not await verify_turnstile(token, client_ip(request)):
        raise HTTPException(status_code=403, detail="captcha_failed")

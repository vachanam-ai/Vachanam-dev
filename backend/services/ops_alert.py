"""Operational alerts that actually reach a human.

`admin_alert.alert_admin` writes a CRITICAL log line and an audit row. Its own
docstring says real delivery is "deferred to TD". That is fine for a forensic
trail and useless as an alert: nobody watches Render logs at 2am, which is
exactly when the events worth alerting on happen.

This module adds the delivery half. It does NOT replace the log or the audit
row — those stay, because the log is the evidence and the email is only the
notification.

Two rules make it safe to switch on:

* **Deduplicated.** The callers are periodic jobs. Without a dedupe key, one
  clinic over its threshold would email every hour, for days, and burn the
  Resend quota Vinay deliberately tightened on 2026-07-12 ("AI-resolved chats
  never email"). Every occurrence is logged; the first one per key is mailed.
* **Best-effort.** Routed through the resilience guard, so a slow or dead
  Resend trips the shared `resend_email` circuit breaker (visible on
  /admin/resilience) instead of hanging a scheduler. Nothing here may ever
  raise into a job, let alone a call (RULE 8).
"""
from __future__ import annotations

import httpx
import structlog

from backend.config import settings

logger = structlog.get_logger()

# How long one alert key stays quiet after it fires. Six hours means a
# persistent condition mails at most four times a day while an hourly job keeps
# re-detecting it, and a genuinely new event the next morning still gets through.
DEDUPE_TTL_SECONDS = 6 * 3600


async def _already_sent(key: str) -> bool:
    """True when this key mailed recently. Redis failure => send (fail LOUD).

    A missed alert is the failure that matters here, so an unreachable Redis
    must not silence us. The cost of the opposite choice is a duplicate email.
    """
    try:
        from backend.redis_client import get_redis

        redis = get_redis()
        # SET NX returns None/False when the key already exists.
        stored = await redis.set(
            f"opsalert:{key}", "1", ex=DEDUPE_TTL_SECONDS, nx=True
        )
        return not stored
    except Exception as exc:  # noqa: BLE001 — never silence an alert on infra trouble
        logger.warning("ops_alert_dedupe_unavailable", error=str(exc)[:120])
        return False


async def send_ops_alert(
    *, event: str, dedupe_key: str, subject: str, body: str
) -> bool:
    """Email the operator once per dedupe_key per DEDUPE_TTL_SECONDS.

    Returns True when an email was actually handed to Resend. Callers use the
    return only for logging/tests — never for control flow.
    """
    logger.warning("ops_alert", alert_event=event, dedupe_key=dedupe_key)

    to = (settings.alert_email or "").strip()
    if not settings.resend_api_key or not to:
        # Unconfigured is a normal local/dev state, not an error.
        logger.info("ops_alert_not_delivered_unconfigured", alert_event=event)
        return False
    if await _already_sent(dedupe_key):
        logger.info(
            "ops_alert_suppressed_duplicate", alert_event=event, dedupe_key=dedupe_key
        )
        return False

    from backend.services.resilience import guard

    async def _post() -> None:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {settings.resend_api_key}"},
                json={
                    "from": settings.resend_from,
                    "to": [to],
                    "subject": subject,
                    "text": body,
                },
            )
            response.raise_for_status()  # the breaker must see a 4xx/5xx

    result = await guard("resend_email", _post, timeout=12, retries=1, fallback=False)
    if result is False:
        logger.warning("ops_alert_send_failed", alert_event=event)
        return False
    logger.info("ops_alert_sent", alert_event=event, dedupe_key=dedupe_key)
    return True

"""OTP issue + verify for signup phone/email validation.

Redis-backed (auto-expiring). One code per (channel, destination). Sending is
pluggable: MSG91 for SMS, SMTP for email. When a provider is not configured
(dev/test), the code is logged and — if otp_dev_echo — returned to the caller
so the whole signup flow is testable without paying for a provider.

Security:
- 6-digit numeric code, TTL from settings.otp_ttl_seconds.
- Max 5 verify attempts per code, then it is burned (anti brute-force).
- Verified flag stored separately so register can confirm both channels passed.
"""
import secrets

import redis.asyncio as aioredis
import structlog

from backend.config import settings

logger = structlog.get_logger()

_MAX_ATTEMPTS = 5


def _redis() -> "aioredis.Redis":
    return aioredis.from_url(settings.redis_url, decode_responses=True)


def _code_key(channel: str, dest: str) -> str:
    # ONE valid code per destination — the latest. Namespace "otpv2:" so it can
    # never collide with the short-lived "otpset:" SET keys from the reverted
    # multi-code experiment (#378) nor legacy "otp:" string keys; both expire on
    # their own 10-min TTL. Single-latest-code is the standard, brute-force-safe
    # shape (a widened valid-code pool multiplies guess odds — #379).
    return f"otpv2:{channel}:{dest}"


def _attempts_key(channel: str, dest: str) -> str:
    return f"otp_attempts:{channel}:{dest}"


def _verified_key(channel: str, dest: str) -> str:
    return f"otp_ok:{channel}:{dest}"


async def issue_code_result(channel: str, dest: str) -> tuple[str | None, bool]:
    """Generate + store a code, send it, and (dev) return it. channel: sms|email."""
    # G16: per-destination send cooldown — one real send per dest per window, so
    # a single attacker can't bomb a victim (and burn provider credits) by
    # spamming /request-otp or /forgot-password. Only throttle when a provider is
    # actually wired; dev/no-provider keeps echoing so the signup flow stays
    # testable. The previously-issued code is still valid (TTL 600s) during the
    # cooldown. SMS = 60s (costs money per send). Email = 25s: it MUST sit below
    # the client's first "resend" tier (30s, Login.jsx) so a legitimate resend
    # the user waited for is never silently swallowed — email is cheap.
    if _provider_configured(channel):
        cooldown = 25 if channel == "email" else 60
        r_cd = _redis()
        try:
            fresh = await r_cd.set(f"otp_cd:{channel}:{dest}", "1", ex=cooldown, nx=True)
        finally:
            await r_cd.aclose()
        if not fresh:
            logger.info("otp_throttled", channel=channel, dest=_mask(dest))
            return None, True

    code = f"{secrets.randbelow(1_000_000):06d}"
    r = _redis()
    try:
        # ONE valid code — the latest overwrites any prior one. When a user
        # requests again / taps resend, ONLY the newest code is valid (they must
        # use the most recent email). This keeps the brute-force guess space at a
        # single 6-digit value; a pool of simultaneously-valid codes would
        # multiply an attacker's odds (#379, reverting #378's multi-code set).
        await r.setex(_code_key(channel, dest), settings.otp_ttl_seconds, code)
        await r.delete(_attempts_key(channel, dest))
        await r.delete(_verified_key(channel, dest))
    finally:
        await r.aclose()

    sent = await _send(channel, dest, code)
    logger.info("otp_issued", channel=channel, dest=_mask(dest), sent=sent)
    # Dev convenience: surface the code so signup is testable without a provider.
    # FAIL CLOSED (bounce F3): only echo when (a) echo is enabled (dev/test, never
    # prod), AND (b) NO provider is configured for this channel. Previously a
    # transient provider failure in any non-prod env (e.g. staging) echoed the
    # real code, letting an attacker self-verify arbitrary phone/email. A
    # configured-but-failing provider must NOT leak the code — return None.
    if settings.otp_echo_enabled and not _provider_configured(channel):
        return code, True
    return None, sent


async def issue_code(channel: str, dest: str) -> str | None:
    """Compatibility wrapper returning only the optional development code."""
    code, _delivered = await issue_code_result(channel, dest)
    return code


def _provider_configured(channel: str) -> bool:
    """True if a real send provider is configured for this channel."""
    if channel == "sms":
        return bool(settings.msg91_auth_key)
    if channel == "email":
        return bool(settings.resend_api_key or settings.smtp_host)
    return False


async def verify_code(channel: str, dest: str, code: str) -> bool:
    """True if code matches and isn't expired/exhausted. Marks channel verified."""
    r = _redis()
    try:
        stored = await r.get(_code_key(channel, dest))
        if stored is None:
            return False
        attempts = await r.incr(_attempts_key(channel, dest))
        await r.expire(_attempts_key(channel, dest), settings.otp_ttl_seconds)
        if attempts > _MAX_ATTEMPTS:
            await r.delete(_code_key(channel, dest))  # burn it
            logger.warning("otp_attempts_exhausted", channel=channel, dest=_mask(dest))
            return False
        if not secrets.compare_digest(stored, code):
            return False
        await r.delete(_code_key(channel, dest))  # one-shot
        await r.setex(_verified_key(channel, dest), settings.otp_ttl_seconds, "1")
        return True
    finally:
        await r.aclose()


async def is_verified(channel: str, dest: str) -> bool:
    """True if this destination recently passed OTP (used by register)."""
    r = _redis()
    try:
        return (await r.get(_verified_key(channel, dest))) == "1"
    finally:
        await r.aclose()


async def clear_verified(channel: str, dest: str) -> None:
    r = _redis()
    try:
        await r.delete(_verified_key(channel, dest))
    finally:
        await r.aclose()


# ── senders ──────────────────────────────────────────────────────────────


async def _send(channel: str, dest: str, code: str) -> bool:
    if channel == "sms":
        return await _send_sms(dest, code)
    if channel == "email":
        return await _send_email(dest, code)
    return False


async def _send_sms(phone: str, code: str) -> bool:
    if not settings.msg91_auth_key:
        return False
    try:
        import httpx

        async with httpx.AsyncClient(timeout=10) as c:
            # MSG91 OTP flow endpoint. mobile must be 91XXXXXXXXXX (no +).
            mobile = phone.lstrip("+")
            r = await c.post(
                "https://control.msg91.com/api/v5/otp",
                params={"mobile": mobile, "otp": code, "sender": settings.msg91_sender_id},
                headers={"authkey": settings.msg91_auth_key},
            )
            return r.status_code == 200
    except Exception as e:
        logger.error("otp_sms_failed", error=str(e))
        return False


async def _send_email_resend(email: str, code: str) -> bool:
    """Send the OTP via Resend's HTTP API. from-domain must be verified in Resend."""
    try:
        import httpx

        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {settings.resend_api_key}"},
                json={
                    "from": settings.resend_from,
                    "to": [email],
                    "subject": "Your Vachanam verification code",
                    "text": (
                        f"Your Vachanam verification code is {code}. "
                        "It expires in 10 minutes. If you did not request this, ignore this email."
                    ),
                },
            )
            ok = r.status_code in (200, 201)
            if not ok:
                logger.error("otp_email_resend_failed", status=r.status_code, body=r.text[:200])
            return ok
    except Exception as e:
        logger.error("otp_email_resend_error", error=str(e))
        return False


async def _send_email(email: str, code: str) -> bool:
    # Prefer Resend (HTTP API) when configured — more reliable from cloud hosts
    # than raw SMTP. Falls back to SMTP when only smtp_host is set.
    if settings.resend_api_key:
        return await _send_email_resend(email, code)
    if not settings.smtp_host:
        return False
    try:
        import asyncio
        from email.message import EmailMessage

        msg = EmailMessage()
        msg["Subject"] = "Your Vachanam verification code"
        msg["From"] = settings.smtp_from
        msg["To"] = email
        msg.set_content(
            f"Your Vachanam verification code is {code}. It expires in 10 minutes."
        )

        def _smtp_send() -> bool:
            import smtplib

            with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as s:
                s.starttls()
                if settings.smtp_user:
                    s.login(settings.smtp_user, settings.smtp_password)
                s.send_message(msg)
            return True

        return await asyncio.to_thread(_smtp_send)
    except Exception as e:
        logger.error("otp_email_failed", error=str(e))
        return False


def _mask(dest: str) -> str:
    return dest[-4:] if dest else "????"

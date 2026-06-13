"""Google OAuth login + JWT issue + logout.

Flow:
1. Frontend gets Google ID token via Sign In With Google
2. Frontend POSTs the ID token to /auth/google
3. Server verifies with Google's public keys (google.oauth2.id_token.verify_oauth2_token)
4. Server looks up the user (first by google_sub, then by email)
5. If user not found → 403 "Not registered" (admin must add them first)
6. If found → issue a Vachanam JWT, return it
7. Frontend stores JWT in localStorage; sends Authorization: Bearer on every request
8. /auth/logout adds the JWT jti to Redis revocation set

No password storage. Google handles password + 2FA.
"""
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

import backend.services.audit_service as _audit_svc
from backend.config import settings
from backend.database import AsyncSessionLocal
from backend.middleware.auth_middleware import (
    CurrentUser,
    create_access_token,
    get_current_user,
    revoke_jwt,
)
from backend.middleware.rate_limit import (
    auth_google_limit,
    check_ip_blocklist,
    default_limit,
    record_failed_login,
)
from backend.models.schema import User

logger = structlog.get_logger()
router = APIRouter()


class GoogleLoginRequest(BaseModel):
    id_token: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds until expiration


@router.post(
    "/google",
    response_model=TokenResponse,
    dependencies=[Depends(check_ip_blocklist), Depends(auth_google_limit)],
)
async def google_login(request: Request, body: GoogleLoginRequest) -> TokenResponse:
    """Verify Google ID token, look up user, issue Vachanam JWT.

    Returns 403 if the IP is in the Redis blocklist (spec §5.6).
    Returns 429 if the IP exceeds 5 attempts/min (spec §6.3).
    Returns 401 if Google rejects the ID token.
    Returns 403 if email is not in the users table (admin must add first).

    Audit:
      - user.login.success on successful login (user_id set, no PII in metadata)
      - user.login.failure on Google token rejection (success=False, email allowed
        per spec §8.2 exception for forensics)
    """
    client_ip = request.client.host if request.client else "127.0.0.1"
    user_agent = request.headers.get("user-agent")

    if not settings.google_oauth_client_id:
        # No OAuth client ID configured — this is a server misconfiguration,
        # NOT a user failure. Do NOT count against the IP blocklist; the
        # deployment is simply unconfigured. Return 401 so clients know auth
        # failed, but don't punish the IP for a server-side config gap.
        logger.error("google_oauth_not_configured")
        raise HTTPException(status_code=401, detail="OAuth not configured")

    try:
        info = google_id_token.verify_oauth2_token(
            body.id_token,
            google_requests.Request(),
            settings.google_oauth_client_id,
        )
    except ValueError as e:
        # ValueError covers invalid signature, wrong audience, expired token, etc.
        # Only REAL Google verification failures count against the IP blocklist
        # (spec §5.6).  Config errors (handled above) do not count.
        logger.warning("google_token_invalid", error=str(e))
        await record_failed_login(client_ip)
        # Audit login failure — spec §8.2 allows "email" key for forensics
        try:
            await _audit_svc.write_audit_row(
                action="user.login.failure",
                ip_address=client_ip,
                user_agent=user_agent,
                metadata={"error": "google_token_invalid"},
                success=False,
            )
        except Exception as audit_err:
            logger.error("audit_write_failed", action="user.login.failure", error=str(audit_err))
        raise HTTPException(status_code=401, detail="Invalid Google token")

    google_sub = info.get("sub")
    email = info.get("email", "")
    name = info.get("name", "")

    if not google_sub or not email:
        raise HTTPException(status_code=401, detail="Google token missing required claims")

    async with AsyncSessionLocal() as db:
        # First try by google_sub (permanent ID — survives email change)
        result = await db.execute(select(User).where(User.google_sub == google_sub))
        user = result.scalar_one_or_none()

        # First-time Google login for a pre-existing email-only user: bind google_sub
        if not user:
            result = await db.execute(select(User).where(User.email == email))
            user = result.scalar_one_or_none()
            if user:
                user.google_sub = google_sub
                if not user.name:
                    user.name = name
                await db.commit()
                await db.refresh(user)

        if not user:
            logger.warning("login_unknown_user", email=email)
            raise HTTPException(
                status_code=403,
                detail="Not registered. Contact your clinic administrator.",
            )

        # Capture values before session closes (DetachedInstanceError prevention)
        user_id = user.id
        user_email = user.email
        user_role = user.role
        token = create_access_token(user)

    logger.info("user_login", user_id=str(user_id), email=user_email, role=user_role)

    # Audit successful login — user_id sufficient, no email in metadata (not login.failure)
    try:
        await _audit_svc.write_audit_row(
            action="user.login.success",
            user_id=user_id,
            ip_address=client_ip,
            user_agent=user_agent,
            success=True,
        )
    except Exception as audit_err:
        logger.error("audit_write_failed", action="user.login.success", error=str(audit_err))

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=settings.jwt_expire_hours * 3600,
    )


class MeResponse(BaseModel):
    user_id: str
    email: str
    role: str
    org_id: str | None
    branch_ids: list[str]
    is_admin: bool


@router.get("/me", response_model=MeResponse, dependencies=[Depends(default_limit)])
async def get_me(current_user: CurrentUser = Depends(get_current_user)) -> MeResponse:
    """Return the current user's identity. Frontend calls this on app load
    to populate user context from a stored JWT."""
    return MeResponse(
        user_id=current_user.user_id,
        email=current_user.email,
        role=current_user.role,
        org_id=current_user.org_id,
        branch_ids=current_user.branch_ids,
        is_admin=current_user.is_admin,
    )


@router.post("/logout", status_code=204, dependencies=[Depends(default_limit)])
async def logout(current_user: CurrentUser = Depends(get_current_user)) -> None:
    """Revoke the current JWT by adding its jti to the Redis revocation set.

    The middleware checks this set on every request, so the token becomes
    invalid immediately even though its signature is still valid until exp.
    """
    from jose import jwt
    # Re-decode just to extract exp; the dependency already validated everything
    # else. We don't want logout to crash if the token is on the verge of expiring.
    from fastapi import Request  # noqa — unused, but documents intent

    # We need the exp claim to set Redis TTL. Get it from a fresh decode.
    # The token bytes aren't in CurrentUser; trade-off vs simpler API. For now
    # use the jwt_expire_hours setting as upper bound — TTL is forgiving.
    ttl_seconds = settings.jwt_expire_hours * 3600
    import time
    exp_timestamp = int(time.time()) + ttl_seconds

    await revoke_jwt(current_user.jti, exp_timestamp)
    logger.info("user_logout", user_id=current_user.user_id, jti=current_user.jti)


# ── Self-serve clinic registration + email/password login ───────────────────


class RegisterRequest(BaseModel):
    clinic_name: str
    owner_name: str
    phone: str
    email: str | None = None
    password: str | None = None
    id_token: str | None = None  # Google alternative to email+password
    plan: str = "clinic"         # solo | clinic | multi
    phone_otp: str | None = None
    email_otp: str | None = None


class LoginRequest(BaseModel):
    email: str
    password: str


class OtpRequest(BaseModel):
    phone: str | None = None
    email: str | None = None


class OtpResponse(BaseModel):
    sent: list[str]
    # Dev only (no provider configured): codes echoed so signup is testable.
    dev_phone_code: str | None = None
    dev_email_code: str | None = None


def _hash_password(password: str) -> str:
    import bcrypt

    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def _verify_password(password: str, password_hash: str) -> bool:
    import bcrypt

    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=201,
    dependencies=[Depends(auth_google_limit)],
)
async def register_clinic(request: Request, body: RegisterRequest) -> TokenResponse:
    """Self-serve clinic signup: creates Organization (14-day trial) + Branch +
    org_admin User in one transaction, then signs the user in.

    Identity: either email+password (bcrypt) or a Google ID token.
    """
    import uuid as _uuid
    from datetime import datetime, timedelta, timezone as _tz

    from backend.models.schema import Branch, Organization

    from backend.services import otp_service
    from backend.services.validators import (
        normalize_email,
        normalize_indian_phone,
        validate_password,
    )

    client_ip = request.client.host if request.client else "unknown"
    await check_ip_blocklist(request)

    # ── Validate shape BEFORE any DB work (clear 422s, no garbage accepted) ──
    if len(body.clinic_name.strip()) < 2:
        raise HTTPException(status_code=422, detail="Clinic name is required")
    if not body.owner_name.strip():
        raise HTTPException(status_code=422, detail="Your name is required")
    try:
        phone = normalize_indian_phone(body.phone)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if body.plan not in ("solo", "clinic", "multi"):
        raise HTTPException(status_code=422, detail="Invalid plan")

    google_sub: str | None = None
    email = (body.email or "").strip().lower()
    if body.id_token:
        if not settings.google_oauth_client_id:
            raise HTTPException(status_code=401, detail="OAuth not configured")
        try:
            info = google_id_token.verify_oauth2_token(
                body.id_token, google_requests.Request(), settings.google_oauth_client_id
            )
        except ValueError:
            await record_failed_login(client_ip)
            raise HTTPException(status_code=401, detail="Invalid Google token")
        google_sub = info.get("sub")
        email = (info.get("email") or "").lower()  # Google-verified
        if not google_sub or not email:
            raise HTTPException(status_code=401, detail="Google token missing required claims")
    else:
        try:
            email = normalize_email(email)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        if not body.password:
            raise HTTPException(status_code=422, detail="Password is required")
        try:
            validate_password(body.password)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

    # ── OTP gate: password signups only. A verified Google ID token is already
    # a strong, Google-authenticated identity — no extra OTP friction
    # (decision: Vinay 2026-06-11). Phone is still format-validated above.
    if not google_sub:
        # M7: a channel already verified on a previous attempt counts. Without
        # this, if the email code was wrong the phone code (consumed first) was
        # already burned, and the retry dead-ended on "Phone not verified" with
        # no way forward. verify_code OR the persisted is_verified flag passes.
        phone_ok = (
            body.phone_otp and await otp_service.verify_code("sms", phone, body.phone_otp)
        ) or await otp_service.is_verified("sms", phone)
        if not phone_ok:
            raise HTTPException(status_code=403, detail="Phone not verified — enter the SMS code")
        email_ok = (
            body.email_otp and await otp_service.verify_code("email", email, body.email_otp)
        ) or await otp_service.is_verified("email", email)
        if not email_ok:
            raise HTTPException(status_code=403, detail="Email not verified — enter the email code")

    async with AsyncSessionLocal() as db:
        existing = (
            await db.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()
        if existing:
            raise HTTPException(
                status_code=409, detail="Account already exists — sign in instead"
            )

        org = Organization(
            name=body.clinic_name.strip(),
            owner_phone=phone,
            owner_email=email,
            plan=body.plan,
            status="trial",
            trial_ends_at=datetime.now(_tz.utc) + timedelta(days=14),
        )
        db.add(org)
        await db.flush()

        branch = Branch(
            org_id=org.id,
            name=body.clinic_name.strip(),
            # WhatsApp wiring is MVP2 — unique placeholder satisfies the NOT NULL
            # constraint until a real number is connected during onboarding.
            whatsapp_number=f"pending-{_uuid.uuid4().hex[:12]}",
            emergency_contact=phone,
        )
        db.add(branch)
        await db.flush()

        user = User(
            org_id=org.id,
            email=email,
            name=body.owner_name.strip(),
            phone=phone,
            role="org_admin",
            branch_ids=[str(branch.id)],
            google_sub=google_sub,
            password_hash=_hash_password(body.password) if body.password else None,
        )
        db.add(user)
        try:
            await db.commit()
        except IntegrityError:
            # M9: two concurrent registers with the same email both pass the
            # SELECT above; one loses the unique constraint race. Return the
            # same 409 the sequential path gives, not a 500.
            await db.rollback()
            raise HTTPException(
                status_code=409, detail="Account already exists — sign in instead"
            )
        await db.refresh(user)

        user_id = user.id
        token = create_access_token(user)

    logger.info("clinic_registered", user_id=str(user_id), org=body.clinic_name[:30])
    try:
        await _audit_svc.write_audit_row(
            action="user.register",
            user_id=user_id,
            ip_address=client_ip,
            user_agent=request.headers.get("user-agent"),
            success=True,
        )
    except Exception as audit_err:
        logger.error("audit_write_failed", action="user.register", error=str(audit_err))

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=settings.jwt_expire_hours * 3600,
    )


@router.post(
    "/login",
    response_model=TokenResponse,
    dependencies=[Depends(auth_google_limit)],
)
async def email_login(request: Request, body: LoginRequest) -> TokenResponse:
    """Email + password sign-in. Same blocklist + failed-login accounting as
    the Google path (5 failures/IP → 1h block)."""
    client_ip = request.client.host if request.client else "unknown"
    await check_ip_blocklist(request)

    email = body.email.strip().lower()
    async with AsyncSessionLocal() as db:
        user = (
            await db.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()
        if user is None or not user.password_hash or not _verify_password(
            body.password, user.password_hash
        ):
            await record_failed_login(client_ip)
            # One message for both cases — no account-existence oracle
            raise HTTPException(status_code=401, detail="Invalid email or password")

        user_id = user.id
        user_role = user.role
        token = create_access_token(user)

    logger.info("user_login", user_id=str(user_id), role=user_role, method="password")
    try:
        await _audit_svc.write_audit_row(
            action="user.login.success",
            user_id=user_id,
            ip_address=client_ip,
            user_agent=request.headers.get("user-agent"),
            success=True,
        )
    except Exception as audit_err:
        logger.error("audit_write_failed", action="user.login.success", error=str(audit_err))

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=settings.jwt_expire_hours * 3600,
    )


@router.post(
    "/request-otp",
    response_model=OtpResponse,
    dependencies=[Depends(auth_google_limit)],
)
async def request_otp(request: Request, body: OtpRequest) -> OtpResponse:
    """Issue OTP codes to phone and/or email for signup verification.

    Validates the destinations first (no point texting a malformed number).
    When no SMS/email provider is configured, codes are returned in the
    response (dev) so the signup flow is fully testable.
    """
    from backend.services import otp_service
    from backend.services.validators import normalize_email, normalize_indian_phone

    client_ip = request.client.host if request.client else "unknown"
    await check_ip_blocklist(request)

    sent: list[str] = []
    dev_phone_code: str | None = None
    dev_email_code: str | None = None

    if body.phone:
        try:
            phone = normalize_indian_phone(body.phone)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        dev_phone_code = await otp_service.issue_code("sms", phone)
        sent.append("sms")

    if body.email:
        try:
            email = normalize_email(body.email)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        dev_email_code = await otp_service.issue_code("email", email)
        sent.append("email")

    if not sent:
        raise HTTPException(status_code=422, detail="Provide a phone or email to verify")

    logger.info("otp_requested", channels=sent, ip=client_ip[-4:])
    return OtpResponse(
        sent=sent, dev_phone_code=dev_phone_code, dev_email_code=dev_email_code
    )

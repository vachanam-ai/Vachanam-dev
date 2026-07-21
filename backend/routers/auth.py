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
import uuid as uuid_mod
from typing import Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from pydantic import BaseModel
from sqlalchemy import select, text
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
    client_ip as _client_ip,
    default_limit,
    record_failed_login,
)
from backend.models.schema import User
from backend.services.turnstile import require_turnstile

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
    client_ip = _client_ip(request)  # iter1 #6: proxy-aware trusted client IP
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


class DeleteAccountRequest(BaseModel):
    # Password for password accounts; Google-only accounts type DELETE instead.
    password: str | None = None
    confirm: str | None = None


@router.post("/delete-account", dependencies=[Depends(default_limit)])
async def delete_account(
    request: Request,
    body: DeleteAccountRequest,
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Owner permanently deletes their clinic and ALL its data (DPDP erasure,
    Vinay 2026-07-17). Irreversible. Requires the owner's password (or the
    typed word DELETE for Google-only accounts). Reuses the FK-safe admin
    cascade; audited (no-FK audit table survives the deletion)."""
    from backend.models.schema import Organization as _Org
    from backend.routers.admin import _hard_delete_org

    if current_user.role != "org_admin":
        raise HTTPException(status_code=403, detail="Only the clinic owner can delete the clinic")
    if not current_user.org_id:
        raise HTTPException(status_code=422, detail="No clinic linked to this login")

    client_ip = _client_ip(request)
    async with AsyncSessionLocal() as db:
        me = (
            await db.execute(select(User).where(User.id == uuid_mod.UUID(current_user.user_id)))
        ).scalar_one_or_none()
        if me is None:
            raise HTTPException(status_code=404, detail="Account not found")
        # Re-authenticate the destructive action (a stolen session must not
        # suffice): password when one exists, else explicit typed DELETE.
        if me.password_hash:
            if not (body.password and _verify_password(body.password, me.password_hash)):
                await record_failed_login(client_ip)
                raise HTTPException(status_code=401, detail="Password incorrect")
        elif (body.confirm or "").strip().upper() != "DELETE":
            raise HTTPException(status_code=422, detail='Type DELETE to confirm')

        org = (
            await db.execute(select(_Org).where(_Org.id == uuid_mod.UUID(current_user.org_id)))
        ).scalar_one_or_none()
        if org is None:
            raise HTTPException(status_code=404, detail="Clinic not found")
        org_id = str(org.id)
        await _hard_delete_org(db, org)
        await db.commit()

    # Kill the session; audit AFTER the commit (audit table has no tenant FKs).
    import time as _time

    await revoke_jwt(current_user.jti, int(_time.time()) + settings.jwt_expire_hours * 3600)
    try:
        await _audit_svc.write_audit_row(
            action="org.self_deleted",
            user_id=uuid_mod.UUID(current_user.user_id),
            ip_address=client_ip,
            user_agent=request.headers.get("user-agent"),
            success=True,
            metadata={"org_id": org_id, "initiated_by": "owner"},
        )
    except Exception as audit_err:
        logger.error("audit_write_failed", action="org.self_deleted", error=str(audit_err))
    logger.info("org_self_deleted", org_id=org_id)
    return {"deleted": True}


# ── Self-serve clinic registration + email/password login ───────────────────


class RegisterRequest(BaseModel):
    clinic_name: str
    owner_name: str
    email: str | None = None
    password: str | None = None
    id_token: str | None = None  # Google alternative to email+password
    # SEC: validated at the boundary — a junk plan used to hit the DB enum and
    # 500; an out-of-enum string is now a clean 422. Keys are the internal plan
    # ids (billing_math.PLANS); "Starter" is the DISPLAY name for solo.
    plan: Literal["lite", "solo", "clinic", "multi"] = "clinic"
    email_otp: str | None = None  # email-OTP verification (Vinay 2026-06-15)
    # DPDP (Vinay 2026-07-17): the clinic (Data Fiduciary) must explicitly
    # accept the Terms + DPA at signup — Vachanam is the Data Processor acting
    # on its instructions. Enforced server-side; recorded in the audit log.
    accepted_terms: bool = False


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


async def _founding_slots_left(db) -> int:
    """#426: remaining founding free-trial slots (0 when the offer is off).

    A slot is consumed by any org created on/after FOUNDING_TRIAL_START that
    ever held a trial (trial_ends_at set) — self-serve grants and admin
    pilots alike. Flip billing_math.FOUNDING_TRIAL_SLOTS to 0 to end it.
    """
    from sqlalchemy import func as _func

    from backend.models.schema import Organization
    from backend.services import billing_math as _bm

    # Trial-for-all (#433 pricing change): the trial is unlimited, so there is
    # always a slot. -1 signals "unlimited" to the public endpoint.
    if getattr(_bm, "TRIAL_FOR_ALL", False):
        return -1
    if _bm.FOUNDING_TRIAL_SLOTS <= 0:
        return 0
    used = (
        await db.execute(
            select(_func.count())
            .select_from(Organization)
            .where(
                Organization.trial_ends_at.is_not(None),
                Organization.created_at >= _bm.FOUNDING_TRIAL_START,
            )
        )
    ).scalar_one()
    return max(0, _bm.FOUNDING_TRIAL_SLOTS - used)


@router.get("/founding-slots", dependencies=[Depends(default_limit)])
async def founding_slots():
    """Public: landing-page trial state. trial_for_all=true → every clinic gets
    the 14-day trial (no scarcity counter); else slots_left is the remaining
    founding-slot count and 0 hides the trial claim."""
    from backend.services import billing_math as _bm

    if getattr(_bm, "TRIAL_FOR_ALL", False):
        return {"trial_for_all": True, "slots_total": -1, "slots_left": -1}
    async with AsyncSessionLocal() as db:
        left = await _founding_slots_left(db)
    return {"trial_for_all": False, "slots_total": _bm.FOUNDING_TRIAL_SLOTS,
            "slots_left": left}


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=201,
    dependencies=[Depends(auth_google_limit), Depends(require_turnstile)],
)
async def register_clinic(request: Request, body: RegisterRequest) -> TokenResponse:
    """Self-serve clinic signup: creates Organization (paused until first payment, #392) + Branch +
    org_admin User in one transaction, then signs the user in.

    Identity: either email+password (bcrypt) or a Google ID token.
    """
    import uuid as _uuid
    from datetime import datetime, timedelta, timezone as _tz

    from backend.services.billing_math import PILOT_DAYS

    from backend.models.schema import Branch, Organization

    from backend.services import otp_service
    from backend.services.validators import (
        normalize_email,
        validate_password,
    )

    client_ip = _client_ip(request)  # iter1 #6: proxy-aware trusted client IP
    await check_ip_blocklist(request)

    # ── Validate shape BEFORE any DB work (clear 422s, no garbage accepted) ──
    if len(body.clinic_name.strip()) < 2:
        raise HTTPException(status_code=422, detail="Clinic name is required")
    if not body.owner_name.strip():
        raise HTTPException(status_code=422, detail="Your name is required")
    if body.plan not in ("lite", "solo", "clinic", "multi"):
        raise HTTPException(status_code=422, detail="Invalid plan")
    # DPDP consent gate: the clinic is the Data Fiduciary; Vachanam processes
    # patient data only on its instructions. No consent, no account.
    if not body.accepted_terms:
        raise HTTPException(
            status_code=422,
            detail="Please accept the Terms of Service and Data Processing Agreement to continue",
        )

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

    # ── OTP gate: EMAIL ONLY (decision: Vinay 2026-06-15, reverses the
    # 2026-06-14 mobile-only choice). Email is now both the login identity AND
    # the verified channel; mobile is no longer collected at signup. A verified
    # Google ID token skips OTP entirely — it is already a strong, Google-
    # authenticated identity.
    if not google_sub:
        # M7: a channel already verified on a previous attempt counts. Without
        # this, a wrong code on retry could burn the already-consumed email code
        # and dead-end on "Email not verified". verify_code OR the persisted
        # is_verified flag passes.
        email_ok = (
            body.email_otp and await otp_service.verify_code("email", email, body.email_otp)
        ) or await otp_service.is_verified("email", email)
        if not email_ok:
            raise HTTPException(status_code=403, detail="Email not verified — enter the code we emailed you")

    async with AsyncSessionLocal() as db:
        existing = (
            await db.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()
        if existing:
            raise HTTPException(
                status_code=409, detail="Account already exists — sign in instead"
            )

        # #426 founding trial (Vinay 2026-07-20): the first
        # FOUNDING_TRIAL_SLOTS signups get the 14-day trial back; everyone
        # after starts paused as per #392 (first payment activates).
        # ponytail: count-then-insert — two simultaneous signups could
        # over-grant one slot; acceptable for a capped goodwill offer.
        # -1 = unlimited (TRIAL_FOR_ALL), >0 = slots remain — both grant it.
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext('vachanam_founding_trial'))")
        )
        _slots = await _founding_slots_left(db)
        founding = _slots != 0
        org = Organization(
            name=body.clinic_name.strip(),
            # Mobile is no longer collected at signup (email-only, Vinay
            # 2026-06-15). owner_phone is NOT NULL, so seed it empty; the owner
            # fills the real clinic phone + emergency contact later in Settings.
            owner_phone="",
            owner_email=email,
            plan=body.plan,
            # #392 (Vinay 2026-07-17: "remove 14-day trial"): no free window
            # outside the founding slots. Paused orgs get the dashboard but
            # the AI line answers with the polite blocked line until the
            # first payment activates. Trial orgs ride the existing trial
            # machinery (TRIAL_MINUTES cap, trial_pause expiry job).
            status="trial" if founding else "paused",
            trial_ends_at=(datetime.now(_tz.utc) + timedelta(days=PILOT_DAYS)) if founding else None,
        )
        db.add(org)
        await db.flush()
        if founding:
            logger.info("founding_trial_granted", org_id=str(org.id))

        branch = Branch(
            org_id=org.id,
            name=body.clinic_name.strip(),
            # WhatsApp wiring is MVP2 — unique placeholder satisfies the NOT NULL
            # constraint until a real number is connected during onboarding.
            whatsapp_number=f"pending-{_uuid.uuid4().hex[:12]}",
            # emergency_contact is set during onboarding/Settings (no phone at signup).
            emergency_contact=None,
        )
        db.add(branch)
        await db.flush()

        user = User(
            org_id=org.id,
            email=email,
            name=body.owner_name.strip(),
            phone=None,
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
            # DPDP consent record: timestamp+IP+UA of the fiduciary's Terms/DPA
            # acceptance live in this row (accepted_terms is gated above).
            metadata={"accepted_terms": True, "terms_context": "signup"},
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
    dependencies=[Depends(auth_google_limit), Depends(require_turnstile)],
)
async def email_login(request: Request, body: LoginRequest) -> TokenResponse:
    """Email + password sign-in. Same blocklist + failed-login accounting as
    the Google path (5 failures/IP → 1h block)."""
    client_ip = _client_ip(request)  # iter1 #6: proxy-aware trusted client IP
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
    dependencies=[Depends(auth_google_limit), Depends(require_turnstile)],
)
async def request_otp(request: Request, body: OtpRequest) -> OtpResponse:
    """Issue OTP codes to phone and/or email for signup verification.

    Validates the destinations first (no point texting a malformed number).
    When no SMS/email provider is configured, codes are returned in the
    response (dev) so the signup flow is fully testable.
    """
    from backend.services import otp_service
    from backend.services.validators import normalize_email, normalize_indian_phone

    client_ip = _client_ip(request)  # iter1 #6: proxy-aware trusted client IP
    await check_ip_blocklist(request)

    sent: list[str] = []
    dev_phone_code: str | None = None
    dev_email_code: str | None = None

    if body.phone:
        try:
            phone = normalize_indian_phone(body.phone)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        dev_phone_code, delivered = await otp_service.issue_code_result("sms", phone)
        if not delivered:
            raise HTTPException(status_code=503, detail="OTP delivery_failed; please retry")
        sent.append("sms")

    if body.email:
        try:
            email = normalize_email(body.email)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        dev_email_code, delivered = await otp_service.issue_code_result("email", email)
        if not delivered:
            raise HTTPException(status_code=503, detail="OTP delivery_failed; please retry")
        sent.append("email")

    if not sent:
        raise HTTPException(status_code=422, detail="Provide a phone or email to verify")

    logger.info("otp_requested", channels=sent, ip=client_ip[-4:])
    return OtpResponse(
        sent=sent, dev_phone_code=dev_phone_code, dev_email_code=dev_email_code
    )


# ── Forgot / reset password (email-OTP, reuses otp_service) ─────────────────


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    email: str
    code: str
    new_password: str


@router.post(
    "/forgot-password",
    response_model=OtpResponse,
    dependencies=[Depends(auth_google_limit), Depends(require_turnstile)],
)
async def forgot_password(request: Request, body: ForgotPasswordRequest) -> OtpResponse:
    """Email a password-reset code. ALWAYS returns the same shape regardless of
    whether the email maps to an account — no account-existence oracle (a code
    is only actually issued when a user exists). Dev (no email provider) echoes
    the code so the flow is testable end-to-end.
    """
    from backend.services import otp_service
    from backend.services.validators import normalize_email

    client_ip = _client_ip(request)
    await check_ip_blocklist(request)

    dev_email_code: str | None = None
    try:
        email = normalize_email(body.email)
    except ValueError:
        # Malformed email — still return the generic "sent" shape (no oracle).
        return OtpResponse(sent=["email"])

    async with AsyncSessionLocal() as db:
        user = (
            await db.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()

    if user is not None:
        dev_email_code = await otp_service.issue_code("email", email)

    logger.info("password_reset_requested", account_exists=bool(user), ip=client_ip[-4:])
    return OtpResponse(sent=["email"], dev_email_code=dev_email_code)


@router.post(
    "/reset-password",
    response_model=TokenResponse,
    dependencies=[Depends(auth_google_limit)],
)
async def reset_password(request: Request, body: ResetPasswordRequest) -> TokenResponse:
    """Verify the email code, set a new bcrypt password, and sign the user in.

    422 on a malformed email / weak password; 401 on a wrong/expired code
    (counts against the IP blocklist like any auth failure).
    """
    from backend.services import otp_service
    from backend.services.validators import normalize_email, validate_password

    client_ip = _client_ip(request)
    await check_ip_blocklist(request)

    try:
        email = normalize_email(body.email)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    try:
        validate_password(body.new_password)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    if not await otp_service.verify_code("email", email, body.code):
        # Do NOT feed the 1-hour IP blocklist from a wrong reset code. A legit
        # user fumbling codes (or entering a SUPERSEDED one — see otp_service,
        # every recent code is now valid) must never earn an IP ban that then
        # rejects even the CORRECT code at check_ip_blocklist before it is ever
        # checked (Vinay 2026-07-15: "both codes, none worked"). Brute force is
        # already bounded by otp_service's 5-attempt-per-code cap + the send
        # cooldown, and reset additionally requires possession of the emailed
        # code, which the IP blocklist does not guard. Diagnostic only (RULE 9:
        # last-4 IP, no email/code).
        logger.info("password_reset_code_rejected", ip=client_ip[-4:])
        raise HTTPException(
            status_code=401,
            detail="That code is wrong or expired — tap Resend for a new one",
        )

    async with AsyncSessionLocal() as db:
        user = (
            await db.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()
        if user is None:
            # Code verified but no user — should not happen; treat as failure.
            raise HTTPException(status_code=404, detail="Account not found")
        user.password_hash = _hash_password(body.new_password)
        user.token_version = int(user.token_version or 0) + 1
        await db.commit()
        await db.refresh(user)
        user_id = user.id
        token = create_access_token(user)

    await otp_service.clear_verified("email", email)  # one-shot — code can't be reused
    logger.info("password_reset", user_id=str(user_id))
    try:
        await _audit_svc.write_audit_row(
            action="user.password_reset",
            user_id=user_id,
            ip_address=client_ip,
            user_agent=request.headers.get("user-agent"),
            success=True,
        )
    except Exception as audit_err:
        logger.error("audit_write_failed", action="user.password_reset", error=str(audit_err))

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=settings.jwt_expire_hours * 3600,
    )

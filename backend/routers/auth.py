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

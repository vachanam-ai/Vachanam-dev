"""JWT authentication middleware.

Issues Vachanam JWTs after Google OAuth verifies the user. Decodes the JWT on
every protected request. Checks a Redis revocation set so /auth/logout can
invalidate a token before its exp.

Per CLAUDE.md and security spec:
- HS256, 32-byte secret from settings.jwt_secret
- 8-hour hard expiration (settings.jwt_expire_hours)
- jti UUID per token for server-side revocation
- branch_ids carried in JWT for branch_guard to enforce isolation
- is_admin claim for require_admin dependency
"""
import uuid
from datetime import datetime, timedelta, timezone

import redis.asyncio as aioredis
import structlog
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt

from backend.config import settings
from backend.models.schema import User

logger = structlog.get_logger()

_ALGORITHM = "HS256"
_bearer = HTTPBearer(auto_error=True)


def _revocation_redis():
    """Per-call Redis client (avoids module-level event-loop binding — see TD-016)."""
    return aioredis.from_url(settings.redis_url, decode_responses=True)


def create_access_token(user: User) -> str:
    """Issue a Vachanam JWT for the given user. Token is valid for jwt_expire_hours."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "role": user.role,
        "org_id": str(user.org_id) if user.org_id else None,
        "branch_ids": user.branch_ids or [],
        "is_admin": bool(user.is_admin),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=settings.jwt_expire_hours)).timestamp()),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=_ALGORITHM)


class CurrentUser:
    """Decoded JWT claims. Created by get_current_user dependency.

    Use .branch_ids list for branch_guard checks. Use .is_admin for admin routes.
    Use .user_id (string UUID) when writing FK columns like Token.marked_by_user_id.
    """

    def __init__(
        self,
        user_id: str,
        email: str,
        role: str,
        org_id: str | None,
        branch_ids: list[str],
        is_admin: bool,
        jti: str,
    ):
        self.user_id = user_id
        self.email = email
        self.role = role
        self.org_id = org_id
        self.branch_ids = branch_ids
        self.is_admin = is_admin
        self.jti = jti


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> CurrentUser:
    """Decode JWT, check revocation list, return CurrentUser. 401 on any failure."""
    token = credentials.credentials
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[_ALGORITHM])
    except JWTError as e:
        logger.warning("jwt_invalid", error=str(e))
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    jti = payload.get("jti")
    if not jti:
        raise HTTPException(status_code=401, detail="Token missing jti")

    # Revocation check — Redis SET key per revoked jti, TTL = remaining exp
    async with _revocation_redis() as r:
        if await r.exists(f"revoked_jwts:{jti}"):
            logger.warning("jwt_revoked", jti=jti)
            raise HTTPException(status_code=401, detail="Token revoked")

    return CurrentUser(
        user_id=payload["sub"],
        email=payload["email"],
        role=payload["role"],
        org_id=payload.get("org_id"),
        branch_ids=payload.get("branch_ids", []) or [],
        is_admin=bool(payload.get("is_admin", False)),
        jti=jti,
    )


async def require_admin(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """Dependency that requires is_admin=True. 403 otherwise. Used on /admin/* routes."""
    if not current_user.is_admin:
        logger.warning("admin_access_denied", user_id=current_user.user_id, email=current_user.email)
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


async def forbid_admin(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """Dependency that blocks super_admin from PII-touching routes.

    Applied to routes that don't use assert_branch_access (e.g. /doctor/me/*).
    Per sub-spec A §5.6: platform admin (Vinay) cannot access clinic data
    outside /admin/* aggregate endpoints. This is a DPDP Act 2023 boundary —
    Vachanam is the Data Processor, clinics are the Data Fiduciary.
    """
    if current_user.role == "super_admin":
        logger.warning(
            "super_admin_pii_access_blocked",
            user_id=current_user.user_id,
            email=current_user.email,
        )
        raise HTTPException(
            status_code=403,
            detail="Use /admin endpoints — platform admin cannot access clinic data",
        )
    return current_user


async def revoke_jwt(jti: str, exp_timestamp: int) -> None:
    """Add a JWT jti to the revocation set with TTL = remaining seconds until exp.

    Called by /auth/logout. Set TTL prevents the revocation set from growing
    unbounded — once a token would have expired anyway, we forget about it.
    """
    now_ts = int(datetime.now(timezone.utc).timestamp())
    ttl = max(exp_timestamp - now_ts, 1)
    async with _revocation_redis() as r:
        await r.set(f"revoked_jwts:{jti}", "1", ex=ttl)
    logger.info("jwt_revoked", jti=jti, ttl=ttl)

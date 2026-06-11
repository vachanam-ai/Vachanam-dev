"""Admin-only router — Phase 4.5 Task 9.

Provides a minimal /admin/ping health check gated by require_admin (is_admin=True
JWT claim). This is a placeholder skeleton for the Phase 8 admin dashboard routes
(spec §8.1 admin.view_* actions). Only Vachanam's own admin (Vinay) reaches these
routes.

Per CLAUDE.md Rule 7: structlog JSON on every significant event.
Per backend-engineer.md: no module-level singletons; all auth via dependency injection.
"""
import structlog
from fastapi import APIRouter, Depends, Request

from backend.middleware.auth_middleware import CurrentUser, require_admin
from backend.middleware.rate_limit import default_limit

logger = structlog.get_logger()

router = APIRouter()


@router.get("/ping")
async def admin_ping(
    request: Request,
    current_user: CurrentUser = Depends(require_admin),
    _rate_limit: None = Depends(default_limit),
) -> dict:
    """Admin liveness check. Returns 200 only when is_admin=True JWT is presented.

    Non-admin JWT → 403 (require_admin raises before this handler runs).
    No JWT → 401 (get_current_user raises before require_admin).
    Expired JWT → 401 (get_current_user raises before require_admin).

    Placeholder for Phase 8 admin dashboard routes. The response shape is
    intentionally minimal — just proves the require_admin dependency works.
    """
    logger.info(
        "admin_ping",
        user_id=current_user.user_id,
        email=current_user.email,
    )
    return {"status": "ok", "admin_user_id": current_user.user_id}


# ── Platform owner management (Vinay + delegates) ───────────────────────────


from pydantic import BaseModel
from sqlalchemy import select

from backend.database import AsyncSessionLocal
from backend.models.schema import User
from backend.services.audit_service import audit


class OwnerOut(BaseModel):
    user_id: str
    email: str
    name: str | None


class OwnerCreate(BaseModel):
    email: str
    name: str
    password: str | None = None  # optional — Google sign-in works with email match


@router.get("/owners", response_model=list[OwnerOut])
async def list_owners(
    request: Request,
    current_user: CurrentUser = Depends(require_admin),
    _rate_limit: None = Depends(default_limit),
) -> list[OwnerOut]:
    """All Vachanam platform owners (super_admin). No clinic PII here."""
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(select(User).where(User.role == "super_admin"))
        ).scalars().all()
        return [OwnerOut(user_id=str(u.id), email=u.email, name=u.name) for u in rows]


@router.post("/owners", response_model=OwnerOut, status_code=201)
@audit("admin.owner_added", resource_type="user")
async def add_owner(
    body: OwnerCreate,
    request: Request,
    current_user: CurrentUser = Depends(require_admin),
    _rate_limit: None = Depends(default_limit),
) -> OwnerOut:
    """Create or promote a Vachanam platform owner. Owner-only — the keys to
    the kingdom are handed out by existing owners, never self-claimed."""
    email = body.email.strip().lower()
    async with AsyncSessionLocal() as db:
        user = (
            await db.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()
        if user:
            user.role = "super_admin"
            user.is_admin = True
            if not user.name:
                user.name = body.name.strip()
        else:
            password_hash = None
            if body.password:
                if len(body.password) < 8:
                    from fastapi import HTTPException

                    raise HTTPException(status_code=422, detail="Password must be 8+ characters")
                from backend.routers.auth import _hash_password

                password_hash = _hash_password(body.password)
            user = User(
                email=email,
                name=body.name.strip(),
                role="super_admin",
                is_admin=True,
                branch_ids=[],
                password_hash=password_hash,
            )
            db.add(user)
        await db.commit()
        await db.refresh(user)

        request.state.audit_resource_id = str(user.id)
        request.state.audit_user_id = current_user.user_id
        logger.info("owner_added", email=email, by=current_user.email)
        return OwnerOut(user_id=str(user.id), email=user.email, name=user.name)

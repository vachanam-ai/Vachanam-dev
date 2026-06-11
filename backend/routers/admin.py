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


# ── Platform: registered clinics + billing roll-up (no patient PII) ─────────


from datetime import datetime, timezone

from backend.models.schema import Branch, Organization


class ClientRow(BaseModel):
    org_id: str
    name: str
    plan: str
    status: str
    owner_email: str
    owner_phone: str
    branches: int
    trial_ends_at: str | None
    days_left: int | None
    created_at: str


class ClientsSummary(BaseModel):
    total_clients: int
    trialing: int
    active: int
    paused: int
    clients: list[ClientRow]


@router.get("/clients", response_model=ClientsSummary)
async def list_clients(
    request: Request,
    current_user: CurrentUser = Depends(require_admin),
    _rate_limit: None = Depends(default_limit),
) -> ClientsSummary:
    """Every registered clinic + plan/billing status. super_admin only.
    Org-level commercial data only — no patient data crosses this boundary."""
    from sqlalchemy import func

    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        orgs = (await db.execute(select(Organization))).scalars().all()
        # branch counts per org in one query
        counts = dict(
            (await db.execute(
                select(Branch.org_id, func.count()).group_by(Branch.org_id)
            )).all()
        )

        rows: list[ClientRow] = []
        trialing = active = paused = 0
        for o in orgs:
            if o.status == "trial":
                trialing += 1
            elif o.status == "active":
                active += 1
            elif o.status == "paused":
                paused += 1
            days_left = None
            if o.trial_ends_at:
                delta = o.trial_ends_at - now
                days_left = max(0, delta.days)
            rows.append(
                ClientRow(
                    org_id=str(o.id),
                    name=o.name,
                    plan=o.plan,
                    status=o.status,
                    owner_email=o.owner_email,
                    owner_phone=o.owner_phone,
                    branches=counts.get(o.id, 0),
                    trial_ends_at=o.trial_ends_at.isoformat() if o.trial_ends_at else None,
                    days_left=days_left,
                    created_at=o.created_at.isoformat() if o.created_at else "",
                )
            )
        rows.sort(key=lambda r: r.created_at, reverse=True)
        return ClientsSummary(
            total_clients=len(orgs),
            trialing=trialing,
            active=active,
            paused=paused,
            clients=rows,
        )

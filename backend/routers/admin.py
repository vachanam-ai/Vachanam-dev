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


# ── Business console: usage, money, growth, controls (no patient PII) ────────


from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import func as _func

from backend.models.schema import BillingCycle, CallLog
from backend.services.billing_math import (
    PLANS,
    call_blocked,
    included_minutes,
    month_expense,
    month_revenue,
)


class OrgBusinessRow(BaseModel):
    org_id: str
    name: str
    plan: str
    status: str
    owner_phone: str
    owner_email: str
    branches: int
    dids: int
    minutes_used: float          # this month
    minutes_included: int
    minutes_left: float
    pct_used: float
    approaching_limit: bool      # >= 80% of included
    exhausted: bool
    hard_block: bool
    blocked_now: bool            # calls being refused right now
    revenue_month: float
    expense_month: float
    profit_month: float
    calls_month: int
    voice_bookings_month: int
    trial_days_left: int | None
    created_at: str


class MonthPoint(BaseModel):
    month: str                   # "2026-01"
    minutes: float
    revenue: float
    expense: float
    new_clients: int


class PaymentRow(BaseModel):
    org_name: str
    plan: str
    cycle_start: str
    cycle_end: str
    amount: float
    minutes_used: int
    status: str
    razorpay_payment_id: str | None
    invoice_number: str | None


class AdminOverview(BaseModel):
    clients_total: int
    clients_new_this_month: int
    clients_new_prev_month: int
    clients_growth_pct: float | None
    minutes_this_month: float
    minutes_prev_month: float
    minutes_growth_pct: float | None
    minutes_all_time: float
    revenue_month: float
    expense_month: float
    profit_month: float
    calls_today: int
    voice_bookings_month: int
    approaching_limit_count: int
    clients: list[OrgBusinessRow]
    monthly: list[MonthPoint]
    payments: list[PaymentRow]


def _month_start(dt: datetime) -> datetime:
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _pct_growth(current: float, previous: float) -> float | None:
    if previous <= 0:
        return None  # no baseline — frontend shows "new"
    return round((current - previous) / previous * 100, 1)


@router.get("/overview", response_model=AdminOverview)
async def admin_overview(
    request: Request,
    current_user: CurrentUser = Depends(require_admin),
    _rate_limit: None = Depends(default_limit),
) -> AdminOverview:
    """The business of Vachanam in one payload: per-clinic usage/limits/money,
    platform totals, month-over-month growth, payment history. super_admin
    only; org-level aggregates only — no patient data crosses this boundary."""
    now = datetime.now(timezone.utc)
    this_month = _month_start(now)
    prev_month = _month_start(this_month - timedelta(days=1))
    six_months_ago = _month_start(this_month - timedelta(days=160))

    async with AsyncSessionLocal() as db:
        orgs = (await db.execute(select(Organization))).scalars().all()
        branches = (await db.execute(select(Branch))).scalars().all()
        org_branches: dict = {}
        branch_org: dict = {}
        for b in branches:
            org_branches.setdefault(b.org_id, []).append(b)
            branch_org[b.id] = b.org_id

        # One pass over 6 months of call_logs — aggregate in Python (call
        # volume at current scale is tiny; revisit with SQL GROUP BY at 100+
        # clinics). RULE 1 note: this is the platform owner's own telemetry,
        # branch rows carry no patient identifiers.
        logs = (
            await db.execute(
                select(
                    CallLog.branch_id,
                    CallLog.started_at,
                    CallLog.duration_seconds,
                    CallLog.booking_made,
                )
                .where(CallLog.started_at >= six_months_ago)
            )
        ).all()

        org_min_this: dict = {}
        org_min_prev: dict = {}
        org_calls_this: dict = {}
        org_bookings_this: dict = {}
        month_minutes: dict = {}
        calls_today = 0
        today = now.date()
        for branch_id, started_at, dur, booked in logs:
            oid = branch_org.get(branch_id)
            if oid is None:
                continue
            mins = (dur or 0) / 60.0
            mkey = started_at.strftime("%Y-%m")
            month_minutes[mkey] = month_minutes.get(mkey, 0.0) + mins
            if started_at >= this_month:
                org_min_this[oid] = org_min_this.get(oid, 0.0) + mins
                org_calls_this[oid] = org_calls_this.get(oid, 0) + 1
                if booked:
                    org_bookings_this[oid] = org_bookings_this.get(oid, 0) + 1
            elif started_at >= prev_month:
                org_min_prev[oid] = org_min_prev.get(oid, 0.0) + mins
            if started_at.date() == today:
                calls_today += 1

        minutes_all_time = (
            await db.execute(select(_func.coalesce(_func.sum(CallLog.duration_seconds), 0)))
        ).scalar_one() / 60.0

        rows: list[OrgBusinessRow] = []
        total_rev = total_exp = 0.0
        approaching_count = 0
        for o in orgs:
            blist = org_branches.get(o.id, [])
            dids = sum(1 for b in blist if b.did_number)
            used = round(org_min_this.get(o.id, 0.0), 1)
            inc = included_minutes(o.plan)
            pct = round(used / inc * 100, 1) if inc else 0.0
            approaching = inc > 0 and used >= 0.8 * inc
            exhausted = inc > 0 and used >= inc
            if approaching and not exhausted:
                approaching_count += 1
            rev = month_revenue(o.plan, o.status, used)
            exp = month_expense(used, dids)
            total_rev += rev
            total_exp += exp
            days_left = None
            if o.status == "trial" and o.trial_ends_at:
                days_left = max(0, (o.trial_ends_at - now).days)
            rows.append(
                OrgBusinessRow(
                    org_id=str(o.id),
                    name=o.name,
                    plan=o.plan,
                    status=o.status,
                    owner_phone=o.owner_phone,
                    owner_email=o.owner_email,
                    branches=len(blist),
                    dids=dids,
                    minutes_used=used,
                    minutes_included=inc,
                    minutes_left=round(max(0.0, inc - used), 1),
                    pct_used=min(pct, 100.0),
                    approaching_limit=approaching,
                    exhausted=exhausted,
                    hard_block=bool(o.hard_block_on_exhaust),
                    blocked_now=call_blocked(
                        o.status, o.plan, bool(o.hard_block_on_exhaust), used
                    )
                    is not None,
                    revenue_month=rev,
                    expense_month=exp,
                    profit_month=round(rev - exp, 2),
                    calls_month=org_calls_this.get(o.id, 0),
                    voice_bookings_month=org_bookings_this.get(o.id, 0),
                    trial_days_left=days_left,
                    created_at=o.created_at.isoformat() if o.created_at else "",
                )
            )
        rows.sort(key=lambda r: r.minutes_used, reverse=True)

        # Growth: clients created per month
        new_this = sum(1 for o in orgs if o.created_at and o.created_at >= this_month)
        new_prev = sum(
            1 for o in orgs if o.created_at and prev_month <= o.created_at < this_month
        )

        # 6-month series (revenue/expense recomputed per month from minutes —
        # plan/DID counts assumed current; good enough for a trend line)
        monthly: list[MonthPoint] = []
        cursor = six_months_ago
        while cursor <= this_month:
            mkey = cursor.strftime("%Y-%m")
            mins = round(month_minutes.get(mkey, 0.0), 1)
            month_new = sum(
                1
                for o in orgs
                if o.created_at and o.created_at.strftime("%Y-%m") == mkey
            )
            # platform-level estimate: every active org's base + pooled overage
            est_rev = sum(
                month_revenue(o.plan, o.status, org_min_this.get(o.id, 0.0))
                for o in orgs
            ) if mkey == this_month.strftime("%Y-%m") else 0.0
            est_exp = round(
                mins * 1.49 + sum(1 for b in branches if b.did_number) * 1000, 2
            )
            monthly.append(
                MonthPoint(
                    month=mkey,
                    minutes=mins,
                    revenue=round(est_rev, 2),
                    expense=est_exp,
                    new_clients=month_new,
                )
            )
            # advance one month
            cursor = _month_start(cursor + timedelta(days=32))
            if len(monthly) > 7:
                break

        payments = (
            await db.execute(
                select(BillingCycle, Organization.name)
                .join(Organization, BillingCycle.org_id == Organization.id)
                .order_by(BillingCycle.cycle_start.desc())
                .limit(20)
            )
        ).all()
        payment_rows = [
            PaymentRow(
                org_name=oname,
                plan=bc.plan,
                cycle_start=bc.cycle_start.isoformat(),
                cycle_end=bc.cycle_end.isoformat(),
                amount=float(bc.base_amount + (bc.overage_amount or 0)),
                minutes_used=bc.minutes_used or 0,
                status=bc.status,
                razorpay_payment_id=bc.razorpay_payment_id,
                invoice_number=bc.invoice_number,
            )
            for bc, oname in payments
        ]

        this_min = round(sum(org_min_this.values()), 1)
        prev_min = round(sum(org_min_prev.values()), 1)
        return AdminOverview(
            clients_total=len(orgs),
            clients_new_this_month=new_this,
            clients_new_prev_month=new_prev,
            clients_growth_pct=_pct_growth(new_this, new_prev),
            minutes_this_month=this_min,
            minutes_prev_month=prev_min,
            minutes_growth_pct=_pct_growth(this_min, prev_min),
            minutes_all_time=round(minutes_all_time, 1),
            revenue_month=round(total_rev, 2),
            expense_month=round(total_exp, 2),
            profit_month=round(total_rev - total_exp, 2),
            calls_today=calls_today,
            voice_bookings_month=sum(org_bookings_this.values()),
            approaching_limit_count=approaching_count,
            clients=rows,
            monthly=monthly,
            payments=payment_rows,
        )


class StatusBody(BaseModel):
    status: str  # active | paused


class PlanBody(BaseModel):
    plan: str  # solo | clinic | multi


class HardBlockBody(BaseModel):
    enabled: bool


async def _load_org(db, org_id: str) -> Organization:
    try:
        import uuid as _uuid

        oid = _uuid.UUID(org_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid org id")
    org = (
        await db.execute(select(Organization).where(Organization.id == oid))
    ).scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return org


@router.post("/orgs/{org_id}/status")
@audit("admin.org_status_changed", resource_type="organization")
async def set_org_status(
    org_id: str,
    body: StatusBody,
    request: Request,
    current_user: CurrentUser = Depends(require_admin),
    _rate_limit: None = Depends(default_limit),
) -> dict:
    """Stop (paused) or resume (active) a clinic's service. Paused orgs'
    calls are answered with a one-line unavailable message and hung up."""
    if body.status not in ("active", "paused"):
        raise HTTPException(status_code=422, detail="status must be active|paused")
    async with AsyncSessionLocal() as db:
        org = await _load_org(db, org_id)
        org.status = body.status
        await db.commit()
        request.state.audit_resource_id = org_id
        logger.info("org_status_changed", org_id=org_id, status=body.status, by=current_user.email)
        return {"org_id": org_id, "status": body.status}


@router.post("/orgs/{org_id}/plan")
@audit("admin.org_plan_changed", resource_type="organization")
async def set_org_plan(
    org_id: str,
    body: PlanBody,
    request: Request,
    current_user: CurrentUser = Depends(require_admin),
    _rate_limit: None = Depends(default_limit),
) -> dict:
    """Upgrade/downgrade a clinic's plan (effective immediately for limits)."""
    if body.plan not in PLANS:
        raise HTTPException(status_code=422, detail="plan must be solo|clinic|multi")
    async with AsyncSessionLocal() as db:
        org = await _load_org(db, org_id)
        org.plan = body.plan
        await db.commit()
        request.state.audit_resource_id = org_id
        logger.info("org_plan_changed", org_id=org_id, plan=body.plan, by=current_user.email)
        return {"org_id": org_id, "plan": body.plan}


@router.post("/orgs/{org_id}/hard-block")
@audit("admin.org_hard_block_changed", resource_type="organization")
async def set_org_hard_block(
    org_id: str,
    body: HardBlockBody,
    request: Request,
    current_user: CurrentUser = Depends(require_admin),
    _rate_limit: None = Depends(default_limit),
) -> dict:
    """Toggle hard-block: when on, calls are refused (politely) the moment
    the month's minutes reach the plan's included bucket."""
    async with AsyncSessionLocal() as db:
        org = await _load_org(db, org_id)
        org.hard_block_on_exhaust = body.enabled
        await db.commit()
        request.state.audit_resource_id = org_id
        logger.info(
            "org_hard_block_changed", org_id=org_id, enabled=body.enabled, by=current_user.email
        )
        return {"org_id": org_id, "hard_block_on_exhaust": body.enabled}

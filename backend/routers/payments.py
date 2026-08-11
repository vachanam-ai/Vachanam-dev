"""
Razorpay Standard Web Checkout integration.

Endpoints:
- POST /api/create-order   — create a Razorpay order (amount in paise, min 100)
- POST /api/verify-payment — verify HMAC-SHA256 signature after checkout

Key secret never leaves the server. Frontend receives only razorpay_key_id (public).
"""
import hashlib
import hmac
import re
import asyncio
import uuid as _uuid
from datetime import date, datetime, timezone

import razorpay
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

import backend.services.audit_service as _audit_svc
from backend.config import settings
from backend.database import get_db
from backend.middleware.auth_middleware import CurrentUser, get_current_user
from backend.middleware.rate_limit import (
    create_order_limit,
    razorpay_webhook_limit,
    verify_payment_limit,
)
from backend.models.schema import Organization
from backend.services.billing_math import (
    PLANS,
    SELLABLE_PLANS,
    add_month,
    effective_price,
    subscription_order_breakdown,
)

logger = structlog.get_logger()
router = APIRouter()


def _extract_org_id(notes: dict | None) -> _uuid.UUID | None:
    """Extract org_id UUID from Razorpay order notes dict.

    Returns None if notes is absent, org_id key is missing, or the value is
    not a valid UUID string. Never raises — org_id is best-effort attribution.
    """
    if not notes:
        return None
    raw = notes.get("org_id")
    if not raw:
        return None
    try:
        return _uuid.UUID(str(raw))
    except (ValueError, AttributeError):
        return None


def _trusted_order_notes(order_id: str) -> dict:
    """Fetch the server-created order back from Razorpay and return ITS notes.

    iter1 #5: /verify-payment is unauthenticated (the HMAC signature is the auth),
    so nothing client-supplied is trusted — the order was created server-side
    with notes set BY US (org_id, plan, billed breakdown; see create_order).
    Best-effort: any failure (creds unset, network, unknown order) → {}, never
    raises."""
    if not order_id:
        return {}
    try:
        client = _get_client()
        order = client.order.fetch(order_id)
    except Exception as e:  # noqa: BLE001 — best-effort
        logger.warning("razorpay_order_fetch_failed", order_id=order_id, error=str(e))
        return {}
    notes = order.get("notes") if isinstance(order, dict) else None
    return notes if isinstance(notes, dict) else {}


def _trusted_org_id_for_order(order_id: str) -> _uuid.UUID | None:
    return _extract_org_id(_trusted_order_notes(order_id) or None)


def _get_client() -> razorpay.Client:
    if not settings.razorpay_key_id or not settings.razorpay_key_secret:
        raise HTTPException(status_code=500, detail="Razorpay credentials not configured")
    return razorpay.Client(auth=(settings.razorpay_key_id, settings.razorpay_key_secret))


class CreateOrderRequest(BaseModel):
    # The amount is NEVER client-controlled (TD-025/G1): a subscription order is
    # for a fixed plan price, derived server-side. The client only names the plan.
    plan: str = Field(..., description="solo | clinic | multi | wa")


class CreateOrderResponse(BaseModel):
    order_id: str
    amount: int
    currency: str
    key_id: str


class CreateSubscriptionResponse(BaseModel):
    subscription_id: str
    amount: int
    currency: str = "INR"
    key_id: str


class VerifySubscriptionRequest(BaseModel):
    razorpay_subscription_id: str
    razorpay_payment_id: str
    razorpay_signature: str


class VerifySubscriptionResponse(BaseModel):
    verified: bool
    payment_id: str
    subscription_id: str


def _autopay_enabled(org: Organization) -> bool:
    return bool(
        org.razorpay_subscription_id
        and getattr(org, "razorpay_subscription_status", None)
        in {"authenticated", "active", "pending"}
    )


async def _recurring_plan(
    db: AsyncSession, client, *, plan: str, amount_paise: int
) -> str:
    """Find or create the immutable Razorpay monthly plan for this exact price."""
    from backend.models.schema import RazorpayPlanMap

    pricing_key = f"{plan}:{amount_paise}:monthly:v1"
    # Two clinics can select the same price at the same instant. Serialize by
    # pricing key before the provider call, otherwise both create immutable
    # Razorpay plans and one then loses the unique DB insert race.
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"razorpay-plan:{pricing_key}"},
    )
    row = (
        await db.execute(
            select(RazorpayPlanMap).where(
                RazorpayPlanMap.pricing_key == pricing_key
            )
        )
    ).scalar_one_or_none()
    if row is not None:
        return row.razorpay_plan_id

    provider = await asyncio.to_thread(
        client.plan.create,
        {
            "period": "monthly",
            "interval": 1,
            "item": {
                "name": f"Vachanam {plan.title()}",
                "amount": amount_paise,
                "currency": "INR",
                "description": "Vachanam clinic subscription",
            },
            "notes": {"pricing_key": pricing_key, "app_plan": plan},
        },
    )
    db.add(
        RazorpayPlanMap(
            pricing_key=pricing_key,
            plan=plan,
            amount_paise=amount_paise,
            razorpay_plan_id=provider["id"],
        )
    )
    await db.commit()
    return provider["id"]


@router.post(
    "/create-subscription",
    response_model=CreateSubscriptionResponse,
    dependencies=[Depends(create_order_limit)],
)
async def create_autopay_subscription(
    req: CreateOrderRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CreateSubscriptionResponse:
    """Create a real recurring mandate, not a one-time order labelled renewal."""
    if current_user.role != "org_admin" or not current_user.org_id:
        raise HTTPException(status_code=403, detail="Only a clinic owner can enable autopay")
    plan = req.plan.strip().lower()
    if plan not in SELLABLE_PLANS:
        raise HTTPException(status_code=422, detail="Unknown plan")

    org = await _load_my_org(current_user, db)
    if _autopay_enabled(org):
        raise HTTPException(status_code=409, detail="Autopay is already enabled")

    wa_addon = await _org_wa_addon(db, org.id)
    breakdown = subscription_order_breakdown(
        plan, 0, 0,
        subscription_started_at=org.subscription_started_at,
        whatsapp_addon=wa_addon,
    )
    client = _get_client()
    if org.razorpay_subscription_id:
        try:
            existing = await asyncio.to_thread(
                client.subscription.fetch, org.razorpay_subscription_id
            )
            existing_status = existing.get("status") or "created"
            existing_notes = existing.get("notes") or {}
            if (
                existing_status == "created"
                and existing_notes.get("plan") == plan
            ):
                return CreateSubscriptionResponse(
                    subscription_id=org.razorpay_subscription_id,
                    amount=breakdown["amount_paise"],
                    key_id=settings.razorpay_key_id,
                )
            if existing_status in {"cancelled", "completed", "expired"}:
                org.razorpay_subscription_id = None
                org.razorpay_subscription_status = existing_status
                await db.commit()
        except Exception as exc:
            logger.warning(
                "razorpay_existing_subscription_fetch_failed",
                error=str(exc)[:160],
            )
    provider_plan_id = await _recurring_plan(
        db, client, plan=plan, amount_paise=breakdown["amount_paise"]
    )
    payload = {
        "plan_id": provider_plan_id,
        "total_count": 120,
        "quantity": 1,
        "customer_notify": True,
        "notes": {
            "org_id": str(org.id),
            "plan": plan,
            "amount_paise": str(breakdown["amount_paise"]),
        },
        "notify_info": {
            "notify_email": org.owner_email,
            "notify_phone": org.owner_phone,
        },
    }
    last = await _latest_cycle(db, org.id)
    if last is not None and last.cycle_end > date.today():
        payload["start_at"] = int(
            datetime(
                last.cycle_end.year, last.cycle_end.month, last.cycle_end.day,
                tzinfo=timezone.utc,
            ).timestamp()
        )
    try:
        subscription = await asyncio.to_thread(client.subscription.create, payload)
    except razorpay.errors.BadRequestError as exc:
        logger.error("razorpay_subscription_rejected", error=str(exc)[:200])
        raise HTTPException(status_code=400, detail="Autopay mandate was rejected")
    except Exception as exc:
        logger.error("razorpay_subscription_create_failed", error=str(exc)[:200])
        raise HTTPException(status_code=502, detail="Could not create autopay mandate")

    org.razorpay_subscription_id = subscription["id"]
    org.razorpay_subscription_status = subscription.get("status") or "created"
    await db.commit()
    return CreateSubscriptionResponse(
        subscription_id=subscription["id"],
        amount=breakdown["amount_paise"],
        key_id=settings.razorpay_key_id,
    )


@router.post(
    "/verify-subscription",
    response_model=VerifySubscriptionResponse,
    dependencies=[Depends(verify_payment_limit)],
)
async def verify_autopay_subscription(
    req: VerifySubscriptionRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> VerifySubscriptionResponse:
    """Verify Checkout's payment|subscription HMAC and bind it to this org."""
    org = await _load_my_org(current_user, db)
    if org.razorpay_subscription_id != req.razorpay_subscription_id:
        raise HTTPException(status_code=403, detail="Subscription does not belong to this clinic")
    expected = hmac.new(
        settings.razorpay_key_secret.encode(),
        f"{req.razorpay_payment_id}|{req.razorpay_subscription_id}".encode(),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, req.razorpay_signature):
        raise HTTPException(status_code=400, detail="Invalid subscription signature")

    client = _get_client()
    subscription = await asyncio.to_thread(
        client.subscription.fetch, req.razorpay_subscription_id
    )
    notes = subscription.get("notes") or {}
    if str(notes.get("org_id")) != str(org.id):
        raise HTTPException(status_code=403, detail="Subscription attribution failed")
    org.razorpay_subscription_status = subscription.get("status") or "authenticated"
    org.razorpay_customer_id = subscription.get("customer_id") or org.razorpay_customer_id
    await db.commit()
    return VerifySubscriptionResponse(
        verified=True,
        payment_id=req.razorpay_payment_id,
        subscription_id=req.razorpay_subscription_id,
    )


class VerifyPaymentRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str
    # Accepted for backward compat but IGNORED for attribution (iter1 #5): org_id
    # is resolved from the trusted server-created Razorpay order, never from here.
    notes: dict | None = None


class VerifyPaymentResponse(BaseModel):
    verified: bool
    payment_id: str
    order_id: str


@router.post(
    "/create-order",
    response_model=CreateOrderResponse,
    dependencies=[Depends(create_order_limit)],
)
async def create_order(
    request: Request,
    req: CreateOrderRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CreateOrderResponse:
    """Create a Razorpay subscription order for the caller's org.

    Auth-gated (TD-025/G1): only a clinic owner with an org can subscribe. The
    amount is server-derived, never client-supplied (#341, Vinay 2026-07-12):
    plan base + the CURRENT paid cycle's overage minutes × ₹5, + 18% GST on the
    whole subtotal. A first activation (trial/paused, no paid cycle) has no
    overage — trial minutes are free service and hard-block on exhaust. The
    order ``notes`` carry org_id + plan + the billed breakdown set BY US, so
    the webhook can trust them when it activates.
    """
    if current_user.role != "org_admin" or not current_user.org_id:
        raise HTTPException(status_code=403, detail="Only a clinic owner can subscribe")

    plan = req.plan.strip().lower()
    plan_def = PLANS.get(plan)
    if plan_def is None:
        raise HTTPException(status_code=422, detail="plan must be lite, solo, clinic or multi")

    # Renewal? Bill the ending cycle's extra usage along with the next cycle.
    org = await _load_my_org(current_user, db)
    used = 0.0
    from backend.models.schema import BillingCycle

    last = (
        await db.execute(
            select(BillingCycle).where(BillingCycle.org_id == org.id)
            .order_by(BillingCycle.cycle_end.desc()).limit(1)
        )
    ).scalar_one_or_none()
    # #353 (Vinay): the pay window LOCKS while a paid cycle runs — it opens
    # 3 days before the cycle ends, and the confirming webhook's new cycle
    # locks it again. Stops accidental n-times payment stacking. Server-side
    # so a stale/bypassed UI can't double-charge.
    if (
        org.status == "active"
        and last is not None
        and (last.cycle_end - date.today()).days > 3
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "Renewal opens 3 days before your current cycle ends "
                f"on {last.cycle_end.isoformat()}"
            ),
        )
    if last is not None:
        used = await _cycle_minutes_used(db, org.id, last.cycle_start, last.cycle_end)
    bd = subscription_order_breakdown(
        plan, used, int(getattr(org, "minutes_adjustment", 0) or 0),
        subscription_started_at=getattr(org, "subscription_started_at", None),
        # Bought WhatsApp mid-cycle? From this renewal on it is ONE invoice
        # (Vinay: "entire billing should come together"), so the renewal order
        # must carry it or the clinic silently gets the feature for free.
        whatsapp_addon=await _org_wa_addon(db, org.id),
    )

    client = _get_client()
    payload = {
        "amount": bd["amount_paise"],
        "currency": "INR",
        "receipt": f"sub_{plan}_{_uuid.uuid4().hex[:10]}",
        # notes set SERVER-SIDE — these are what the webhook trusts for activation
        "notes": {
            "org_id": current_user.org_id,
            "plan": plan,
            "base": str(bd["base"]),
            "overage_minutes": str(bd["overage_minutes"]),
            "overage_amount": str(bd["overage_amount"]),
            "gst": str(bd["gst"]),
        },
    }

    try:
        order = client.order.create(payload)
    except razorpay.errors.BadRequestError as e:
        # G12: log the detail, return a generic message — the raw provider error
        # can carry internal IDs/config hints.
        logger.error("razorpay_order_bad_request", error=str(e), plan=plan)
        raise HTTPException(status_code=400, detail="Order rejected by payment provider")
    except razorpay.errors.SignatureVerificationError as e:
        logger.error("razorpay_auth_failed", error=str(e))
        raise HTTPException(status_code=401, detail="Razorpay auth failed")
    except Exception as e:
        logger.error("razorpay_order_create_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Order creation failed")

    logger.info(
        "razorpay_order_created", order_id=order["id"], plan=plan, org_id=current_user.org_id
    )
    return CreateOrderResponse(
        order_id=order["id"],
        amount=order["amount"],
        currency=order["currency"],
        key_id=settings.razorpay_key_id,
    )


# ── Clinic self-serve plan change (effective next billing cycle) ────────────


class PlanInfo(BaseModel):
    plan: str
    status: str
    pending_plan: str | None
    pending_plan_effective: str | None  # ISO date the pending change applies
    cycle_end: str | None = None  # ISO date the current PAID cycle ends (renewal day)
    last_payment_date: str | None = None  # ISO date the last payment was confirmed (#353)
    gstin: str | None = None  # clinic's GSTIN (shown on invoices)
    # #391 launch offer: the base this org pays NEXT charge (offer-aware) and
    # whether it is the first-3-months offer price — UI shows exact numbers.
    next_base_rupees: int = 0
    is_offer: bool = False
    # WhatsApp: bundled by the plan, bought as the ₹1,499 add-on, or arriving
    # with a scheduled plan change. The Settings card renders one of the three.
    whatsapp_included: bool = False
    whatsapp_addon: bool = False
    whatsapp_included_pending: bool = False
    # End-of-cycle cancellation: the date service stops, or None.
    cancellation_effective: str | None = None
    autopay_enabled: bool = False
    autopay_status: str | None = None


class PlanChangeRequest(BaseModel):
    plan: str


async def _load_my_org(current_user: CurrentUser, db: "AsyncSession") -> Organization:
    if not current_user.org_id:
        raise HTTPException(status_code=403, detail="No organization")
    org = (
        await db.execute(
            select(Organization).where(Organization.id == _uuid.UUID(current_user.org_id))
        )
    ).scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return org


async def _cycle_minutes_used(db: AsyncSession, org_id, start: date, end: date) -> float:
    """Voice minutes the org consumed in [start, end) — call_logs summed across
    its branches. This is the metering behind per-minute overage billing."""
    from sqlalchemy import func

    from backend.models.schema import Branch, CallLog

    start_dt = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
    end_dt = datetime(end.year, end.month, end.day, tzinfo=timezone.utc)
    secs = (
        await db.execute(
            select(func.coalesce(func.sum(CallLog.duration_seconds), 0))
            .join(Branch, Branch.id == CallLog.branch_id)
            .where(
                Branch.org_id == org_id,
                CallLog.started_at >= start_dt,
                CallLog.started_at < end_dt,
            )
        )
    ).scalar_one()
    return float(secs or 0) / 60.0


async def _latest_cycle(db: AsyncSession, org_id):
    """Latest BillingCycle row (by cycle_end) or None."""
    from backend.models.schema import BillingCycle

    return (
        await db.execute(
            select(BillingCycle)
            .where(BillingCycle.org_id == org_id)
            .order_by(BillingCycle.cycle_end.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


def _metering_period(org: Organization, today: date) -> tuple[date, date]:
    """The window being metered RIGHT NOW when no BillingCycle row exists yet.

    Vinay 2026-08-07: "billing page is completely empty." It was, and only for
    the clinics that matter most — the ones still deciding whether to pay. The
    first BillingCycle row is written by the first payment, and usage was read
    only from inside a cycle, so a clinic with no cycle reported zero minutes
    no matter how many calls it had actually taken. The minutes were real; the
    invoice was the thing that did not exist yet.

    Anchored on the subscription/signup day, the same anchor a real cycle
    uses, so the figure does not jump the moment the first cycle is created.
    """
    from backend.services.billing_math import add_month

    anchor = None
    if org.subscription_started_at is not None:
        anchor = org.subscription_started_at.date()
    elif org.created_at is not None:
        anchor = org.created_at.date()
    if anchor is None or anchor > today:
        return today, add_month(today)
    start = anchor
    while True:
        nxt = add_month(start)
        if nxt > today:
            return start, nxt
        start = nxt


async def _current_cycle(db: AsyncSession, org_id, today: date | None = None):
    """Paid cycle containing today; future renewals are never current.

    A clinic may pay a renewal early. Ordering all cycles by cycle_end made
    that future row replace the cycle being consumed today, which reset the
    billing screen's usage and moved its renewal date forward by a month.
    """
    from backend.models.schema import BillingCycle

    today = today or date.today()
    return (
        await db.execute(
            select(BillingCycle)
            .where(
                BillingCycle.org_id == org_id,
                BillingCycle.cycle_start <= today,
                BillingCycle.cycle_end > today,
                BillingCycle.status == "paid",
            )
            .order_by(BillingCycle.cycle_start.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _latest_cycle_end(db: AsyncSession, org_id) -> date | None:
    last = await _latest_cycle(db, org_id)
    return last.cycle_end if last else None


def _plan_info(
    org: Organization,
    current_cycle=None,
    wa_addon: bool = False,
    latest_payment_cycle=None,
) -> "PlanInfo":
    from backend.services.billing_math import WHATSAPP_PLANS

    plan_key = current_cycle.plan if current_cycle is not None else org.plan
    payment_cycle = latest_payment_cycle or current_cycle
    _base, _is_offer = effective_price(plan_key, org.subscription_started_at)
    return PlanInfo(
        autopay_enabled=_autopay_enabled(org),
        autopay_status=getattr(org, "razorpay_subscription_status", None),
        next_base_rupees=_base,
        is_offer=_is_offer,
        # Three distinct states, because offering to SELL a clinic something
        # their plan already includes is worse than not offering it at all.
        whatsapp_included=plan_key in WHATSAPP_PLANS,
        whatsapp_addon=bool(wa_addon),
        whatsapp_included_pending=(org.pending_plan or "") in WHATSAPP_PLANS,
        plan=plan_key,
        status=org.status,
        pending_plan=org.pending_plan,
        pending_plan_effective=(
            org.pending_plan_effective.isoformat() if org.pending_plan_effective else None
        ),
        cancellation_effective=(
            org.cancellation_effective.isoformat()
            if org.cancellation_effective else None
        ),
        cycle_end=current_cycle.cycle_end.isoformat() if current_cycle else None,
        # The cycle row is created the moment the webhook confirms payment —
        # its created_at IS the payment timestamp (#353 "last payment date").
        last_payment_date=(
            payment_cycle.created_at.date().isoformat()
            if payment_cycle is not None and payment_cycle.created_at
            else None
        ),
        gstin=getattr(org, "gstin", None),
    )


@router.get("/plan", response_model=PlanInfo)
async def get_plan(
    current_user: CurrentUser = Depends(get_current_user),
    db: "AsyncSession" = Depends(get_db),
) -> "PlanInfo":
    """Caller's current plan + any scheduled change + current cycle end."""
    org = await _load_my_org(current_user, db)
    return _plan_info(
        org,
        await _current_cycle(db, org.id),
        await _org_wa_addon(db, org.id),
        await _latest_cycle(db, org.id),
    )


class BillingCycleOut(BaseModel):
    """One past cycle, for the billing history table."""
    cycle_start: str
    cycle_end: str
    plan: str
    base_amount: int
    minutes_used: int
    overage_minutes: int
    overage_amount: int
    total: int
    status: str
    invoice_number: str | None = None


class BillingSummary(BaseModel):
    """Everything the Billing page shows, in one call.

    Vinay 2026-08-07 asked for a dedicated billing page: "this is money part
    right". Money screens must not make the reader do arithmetic, so the
    server sends the finished figures rather than parts the UI adds up — the
    UI can never disagree with the invoice that way.
    """
    plan: str
    plan_label: str
    next_plan: str = ""
    next_plan_label: str = ""
    status: str
    cycle_start: str | None = None
    cycle_end: str | None = None
    has_billed: bool = False
    included_minutes: int = 0
    minutes_used: int = 0
    overage_minutes: int = 0
    overage_rate: float = 0.0
    overage_amount: int = 0
    base_next: int = 0
    whatsapp_addon_amount: int = 0
    gst_amount: float = 0.0
    total_next: int = 0
    is_offer: bool = False
    autopay_enabled: bool = False
    cancellation_effective: str | None = None
    history: list[BillingCycleOut] = []


@router.get("/billing/summary", response_model=BillingSummary)
async def billing_summary(
    current_user: CurrentUser = Depends(get_current_user),
    db: "AsyncSession" = Depends(get_db),
) -> "BillingSummary":
    """Current cycle usage + what the next charge will be + past cycles."""
    from backend.models.schema import BillingCycle
    from backend.services.billing_math import (
        _gst_on, PLANS, WHATSAPP_ADDON_PLANS, WHATSAPP_ADDON_RUPEES,
        effective_price,
    )

    org = await _load_my_org(current_user, db)
    current = await _current_cycle(db, org.id)
    plan_key = (current.plan if current is not None else org.plan) or "clinic"
    plan_def = PLANS.get(plan_key)
    wa_addon = await _org_wa_addon(db, org.id)

    # Meter the CURRENT period whether or not it has been invoiced yet — see
    # _metering_period. A clinic that has not paid still makes calls, and those
    # minutes are what tells them whether the plan fits.
    if current is not None:
        period_start, period_end = current.cycle_start, current.cycle_end
    else:
        period_start, period_end = _metering_period(org, date.today())
    used = await _cycle_minutes_used(db, org.id, period_start, period_end)
    used_min = int(round(used))
    included = plan_def.included_minutes if plan_def else 0
    over_min = max(0, used_min - included)
    rate = plan_def.overage_per_min if plan_def else 0.0
    over_amt = int(round(over_min * rate))

    next_plan_key = (org.pending_plan or plan_key).lower()
    next_plan_def = PLANS.get(next_plan_key)
    if org.cancellation_effective:
        # Cancellation stops the fixed renewal, but current-cycle overage is
        # still owed. Never show a full plan charge after promising an exit.
        base_next, is_offer = 0, False
        addon_amt = 0
    else:
        base_next, is_offer = effective_price(
            next_plan_key, org.subscription_started_at
        )
        addon_amt = (
            WHATSAPP_ADDON_RUPEES
            if wa_addon and next_plan_key in WHATSAPP_ADDON_PLANS
            else 0
        )
    subtotal = base_next + addon_amt + over_amt
    gst = _gst_on(subtotal)

    rows = (
        await db.execute(
            select(BillingCycle)
            .where(BillingCycle.org_id == org.id)
            .order_by(BillingCycle.cycle_start.desc())
            .limit(24)
        )
    ).scalars().all()

    return BillingSummary(
        plan=plan_key,
        plan_label=(plan_def.display_name if plan_def else plan_key),
        next_plan=next_plan_key,
        next_plan_label=(
            next_plan_def.display_name if next_plan_def else next_plan_key
        ),
        status=org.status or "paused",
        cycle_start=period_start.isoformat(),
        cycle_end=period_end.isoformat(),
        # Whether that period has ever been invoiced. The dates above are real
        # either way, but "Renews on" and "First charge on" are different
        # sentences and the page must not promise a renewal to a clinic that
        # has not paid once.
        has_billed=current is not None,
        included_minutes=included,
        minutes_used=used_min,
        overage_minutes=over_min,
        overage_rate=rate,
        overage_amount=over_amt,
        base_next=int(base_next),
        whatsapp_addon_amount=addon_amt,
        gst_amount=gst,
        total_next=int(round(subtotal + gst)),
        is_offer=bool(is_offer),
        autopay_enabled=_autopay_enabled(org),
        cancellation_effective=(
            org.cancellation_effective.isoformat()
            if org.cancellation_effective else None
        ),
        history=[
            BillingCycleOut(
                cycle_start=c.cycle_start.isoformat(),
                cycle_end=c.cycle_end.isoformat(),
                plan=c.plan,
                base_amount=c.base_amount,
                minutes_used=c.minutes_used or 0,
                overage_minutes=c.overage_minutes or 0,
                overage_amount=c.overage_amount or 0,
                total=(c.base_amount or 0) + (c.overage_amount or 0),
                status=c.status,
                invoice_number=c.invoice_number,
            )
            for c in rows
        ],
    )


async def _enable_whatsapp_addon(
    db: "AsyncSession", notes: dict, payment_id: str
) -> str:
    """Enable the paid branch and keep an existing mandate recurring."""
    from backend.models.schema import AddonPurchase, Branch
    from backend.services.billing_math import whatsapp_addon_order_breakdown

    branch_id = (notes or {}).get("branch_id")
    org_id = (notes or {}).get("org_id")
    if not branch_id or not org_id:
        logger.error("wa_addon_notes_incomplete", payment_id=payment_id)
        return "invalid_notes"
    branch = (
        await db.execute(
            select(Branch).where(
                Branch.id == _uuid.UUID(str(branch_id)),
                Branch.org_id == _uuid.UUID(str(org_id)),
            )
        )
    ).scalar_one_or_none()
    if branch is None:
        logger.error("wa_addon_branch_missing", payment_id=payment_id)
        return "branch_missing"

    bd = whatsapp_addon_order_breakdown()
    already = (
        await db.execute(
            select(AddonPurchase).where(
                AddonPurchase.razorpay_payment_id == payment_id
            )
        )
    ).scalar_one_or_none()
    if branch.whatsapp_addon:
        if already is None:
            db.add(AddonPurchase(
                org_id=branch.org_id,
                branch_id=branch.id,
                kind="whatsapp_addon",
                amount=int(bd["base"]),
                gst=int(round(bd["gst"])),
                razorpay_payment_id=payment_id,
            ))
        await db.commit()
        logger.info("wa_addon_already_on", branch_id=str(branch.id))
        return "already_enabled"

    # Update the next recurring debit before exposing the feature. If Razorpay
    # rejects the update, no local entitlement is committed and its signed
    # webhook can retry safely.
    org = await db.get(Organization, branch.org_id)
    if org is not None and _autopay_enabled(org):
        recurring = subscription_order_breakdown(
            org.plan,
            0,
            0,
            subscription_started_at=org.subscription_started_at,
            whatsapp_addon=True,
        )
        client = _get_client()
        provider_plan_id = await _recurring_plan(
            db,
            client,
            plan=org.plan,
            amount_paise=recurring["amount_paise"],
        )
        await asyncio.to_thread(
            client.subscription.edit,
            org.razorpay_subscription_id,
            {
                "plan_id": provider_plan_id,
                "schedule_change_at": "cycle_end",
                "customer_notify": True,
            },
        )

    if already is None:
        db.add(AddonPurchase(
            org_id=branch.org_id,
            branch_id=branch.id,
            kind="whatsapp_addon",
            amount=int(bd["base"]),
            gst=int(round(bd["gst"])),
            razorpay_payment_id=payment_id,
        ))
    branch.whatsapp_addon = True
    await db.commit()
    try:
        from backend.services.clinic_cache import invalidate

        await invalidate(branch.id)
    except Exception as e:  # noqa: BLE001 - cache is an accelerator
        logger.warning("wa_addon_cache_invalidate_failed", error=str(e)[:120])
    logger.info("wa_addon_enabled", branch_id=str(branch.id), payment_id=payment_id)
    return "addon_enabled"


async def _org_wa_addon(db: "AsyncSession", org_id) -> bool:
    """True when any branch of this org has bought the WhatsApp add-on.

    The flag lives per BRANCH because WhatsApp is provisioned per number, but
    the billing card is per org — one bought number is enough to show it as on.
    """
    from backend.models.schema import Branch

    row = (
        await db.execute(
            select(Branch.id).where(
                Branch.org_id == org_id, Branch.whatsapp_addon.is_(True)
            ).limit(1)
        )
    ).first()
    return row is not None


@router.post(
    "/whatsapp-addon/order",
    response_model=CreateOrderResponse,
    dependencies=[Depends(create_order_limit)],
)
async def create_whatsapp_addon_order(
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CreateOrderResponse:
    """One-off ₹1,499 that switches WhatsApp on for the rest of this cycle.

    From the NEXT renewal the amount is folded into the plan invoice by
    subscription_order_breakdown, so a clinic never manages two subscriptions
    (Vinay 2026-08-03: "from next month on entire billing should come
    together"). Replaces the super-admin linking script — a clinic can now turn
    WhatsApp on itself, which is the only way this scales past clinic #1.

    Amount is server-derived and the branch is resolved server-side: neither is
    client-supplied, so a tampered request cannot buy a cheaper add-on or turn
    it on for somebody else's branch (RULE 1).
    """
    from backend.models.schema import Branch
    from backend.services.billing_math import (
        WHATSAPP_ADDON_PLANS, WHATSAPP_PLANS, whatsapp_addon_order_breakdown,
    )

    if current_user.role != "org_admin" or not current_user.org_id:
        raise HTTPException(status_code=403, detail="Only a clinic owner can buy this")

    org = await _load_my_org(current_user, db)
    if org.plan in WHATSAPP_PLANS:
        raise HTTPException(
            status_code=409, detail="WhatsApp is already included in your plan"
        )
    if org.plan not in WHATSAPP_ADDON_PLANS:
        raise HTTPException(
            status_code=409, detail="This plan cannot take the WhatsApp add-on"
        )
    if org.status != "active":
        raise HTTPException(
            status_code=409,
            detail="Activate your plan first — WhatsApp is billed alongside it",
        )

    branches = (
        await db.execute(select(Branch).where(Branch.org_id == org.id))
    ).scalars().all()
    if not branches:
        raise HTTPException(status_code=409, detail="No branch to enable WhatsApp on")
    unbought = [b for b in branches if not b.whatsapp_addon]
    if not unbought:
        raise HTTPException(status_code=409, detail="WhatsApp add-on is already active")
    if len(unbought) > 1:
        # Per NUMBER, so a multi-branch org must say which. Not guessed: the
        # wrong guess bills for one number and enables another.
        raise HTTPException(
            status_code=409,
            detail="Several branches — enable WhatsApp per branch from that branch's settings",
        )
    branch = unbought[0]

    # Razorpay does not permit in-place amount/plan changes for bank eMandates.
    # Refuse before taking the one-off add-on payment; otherwise the clinic
    # could pay successfully and only then learn its recurring mandate cannot
    # include the add-on.
    if _autopay_enabled(org):
        try:
            subscription = await asyncio.to_thread(
                _get_client().subscription.fetch,
                org.razorpay_subscription_id,
            )
        except Exception as exc:
            logger.error("wa_addon_mandate_preflight_failed", error=str(exc)[:180])
            raise HTTPException(
                status_code=502,
                detail="Could not confirm the current autopay mandate",
            ) from exc
        payment_method = str(subscription.get("payment_method") or "").lower()
        if payment_method in {"emandate", "nach"}:
            raise HTTPException(
                status_code=409,
                detail=(
                    "This bank mandate cannot be changed. Choose a plan that "
                    "includes WhatsApp and create a new autopay mandate."
                ),
            )

    bd = whatsapp_addon_order_breakdown()
    client = _get_client()
    try:
        order = client.order.create({
            "amount": bd["amount_paise"],
            "currency": "INR",
            "receipt": f"waaddon_{_uuid.uuid4().hex[:10]}",
            # notes are SERVER-SET — verify/webhook trust only these.
            "notes": {
                "org_id": str(org.id),
                "kind": "whatsapp_addon",
                "branch_id": str(branch.id),
                "base": str(bd["base"]),
                "gst": str(bd["gst"]),
            },
        })
    except razorpay.errors.BadRequestError as e:
        logger.error("razorpay_wa_addon_order_failed", error=str(e)[:200])
        raise HTTPException(status_code=502, detail="Could not start the payment") from e

    logger.info(
        "wa_addon_order_created",
        org_id=str(org.id), branch_id=str(branch.id), amount_paise=bd["amount_paise"],
    )
    request.state.audit_resource_id = order["id"]
    return CreateOrderResponse(
        order_id=order["id"],
        amount=bd["amount_paise"],
        currency="INR",
        key_id=settings.razorpay_key_id,
    )


@router.post("/plan-change", response_model=PlanInfo)
async def change_plan(
    req: PlanChangeRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: "AsyncSession" = Depends(get_db),
) -> "PlanInfo":
    """Schedule a plan change for the next billing cycle.

    Anniversary billing (Vinay 2026-07-12): a clinic's cycle starts the day
    they pay, not the 1st of the month. So a scheduled change applies on the
    CURRENT PAID CYCLE'S end date — never mid-cycle, so a downgrade can't
    shrink minutes already paid for. A clinic with no future paid cycle
    (trial / paused — nothing paid to protect) switches immediately.
    Selecting the current plan cancels a pending change. A daily job applies
    the change once its effective date arrives.
    """
    if current_user.role != "org_admin":
        raise HTTPException(status_code=403, detail="Only a clinic owner can change the plan")
    plan = req.plan.strip().lower()
    if plan not in SELLABLE_PLANS:
        raise HTTPException(
            status_code=422,
            detail="plan must be solo, clinic, multi or wa",
        )

    org = await _load_my_org(current_user, db)
    cycle_end = await _latest_cycle_end(db, org.id)

    # Keep provider and application state in one transaction boundary: if
    # Razorpay rejects a scheduled plan update, do not let our database claim
    # a different plan will take effect.
    if org.razorpay_subscription_id:
        try:
            client = _get_client()
            if plan == org.plan:
                if org.pending_plan:
                    await asyncio.to_thread(
                        client.subscription.cancel_scheduled_changes,
                        org.razorpay_subscription_id,
                    )
            else:
                # A Razorpay plan is the repeating FIXED charge. Current-cycle
                # overage must never be baked into every future month.
                breakdown = subscription_order_breakdown(
                    plan, 0, 0,
                    subscription_started_at=org.subscription_started_at,
                    whatsapp_addon=await _org_wa_addon(db, org.id),
                )
                provider_plan_id = await _recurring_plan(
                    db, client, plan=plan,
                    amount_paise=breakdown["amount_paise"],
                )
                await asyncio.to_thread(
                    client.subscription.edit,
                    org.razorpay_subscription_id,
                    {
                        "plan_id": provider_plan_id,
                        "schedule_change_at": (
                            "cycle_end"
                            if cycle_end and cycle_end > date.today()
                            else "now"
                        ),
                        "customer_notify": True,
                    },
                )
        except Exception as exc:
            logger.error("autopay_plan_change_failed", error=str(exc)[:180])
            raise HTTPException(
                status_code=502,
                detail="Razorpay could not schedule this autopay plan change",
            )

    if plan == org.plan:
        # No-op / cancel a previously scheduled change.
        org.pending_plan = None
        org.pending_plan_effective = None
    else:
        if cycle_end and cycle_end > date.today():
            org.pending_plan = plan
            org.pending_plan_effective = cycle_end
        else:
            # Nothing paid-for to protect — apply now.
            org.plan = plan
            org.pending_plan = None
            org.pending_plan_effective = None
    await db.commit()
    await db.refresh(org)
    logger.info(
        "plan_change_scheduled",
        org_id=current_user.org_id,
        from_plan=org.plan,
        to_plan=org.pending_plan,
        effective=org.pending_plan_effective.isoformat() if org.pending_plan_effective else None,
    )
    return _plan_info(
        org,
        await _current_cycle(db, org.id),
        await _org_wa_addon(db, org.id),
        await _latest_cycle(db, org.id),
    )


@router.post("/plan-change/cancel", response_model=PlanInfo)
async def cancel_plan_change(
    current_user: CurrentUser = Depends(get_current_user),
    db: "AsyncSession" = Depends(get_db),
) -> "PlanInfo":
    """Cancel a scheduled plan switch, including from a retired plan."""
    if current_user.role != "org_admin":
        raise HTTPException(status_code=403, detail="Only a clinic owner can change the plan")
    org = await _load_my_org(current_user, db)
    if org.pending_plan and org.razorpay_subscription_id:
        try:
            await asyncio.to_thread(
                _get_client().subscription.cancel_scheduled_changes,
                org.razorpay_subscription_id,
            )
        except Exception as exc:
            logger.error("autopay_plan_change_cancel_failed", error=str(exc)[:180])
            raise HTTPException(
                status_code=502,
                detail="Razorpay could not cancel this scheduled plan change",
            ) from exc
    org.pending_plan = None
    org.pending_plan_effective = None
    await db.commit()
    await db.refresh(org)
    logger.info("plan_change_cancelled", org_id=current_user.org_id)
    return _plan_info(
        org,
        await _current_cycle(db, org.id),
        await _org_wa_addon(db, org.id),
        await _latest_cycle(db, org.id),
    )


class CancelRequest(BaseModel):
    # False undoes a scheduled cancellation — a clinic must be able to change
    # its mind for as long as it is still paying.
    cancel: bool = True


@router.post("/plan-cancel", response_model=PlanInfo)
async def cancel_subscription(
    req: CancelRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: "AsyncSession" = Depends(get_db),
) -> "PlanInfo":
    """Schedule (or undo) a full cancellation at the end of the paid cycle.

    Vinay 2026-08-07: "they can exit completely. and effect will take place
    from coming month (after their current cycle ends)."

    Service is NOT cut here. The clinic paid for the cycle it is in and keeps
    everything until it ends; a daily job flips the org to `cancelled` when the
    date arrives. Cancelling mid-cycle would be taking money for a service we
    then withdrew.

    Dropping VOICE but keeping WhatsApp is NOT this endpoint — that is
    /api/plan-change to `wa`, which the same end-of-cycle rule already covers.
    Cancelling also clears any pending plan change: there is nothing left to
    change into.
    """
    if current_user.role != "org_admin":
        raise HTTPException(
            status_code=403, detail="Only a clinic owner can cancel the subscription"
        )
    org = await _load_my_org(current_user, db)

    if not req.cancel:
        if org.razorpay_subscription_id and org.cancellation_effective:
            # Razorpay's cancel_scheduled_changes endpoint cancels a PLAN
            # UPDATE, not a subscription cancellation. Razorpay explicitly
            # does not reactivate a cancelled subscription, so pretending an
            # undo succeeded would allow the clinic to lapse unexpectedly.
            raise HTTPException(
                status_code=409,
                detail=(
                    "Razorpay has already scheduled this autopay cancellation. "
                    "After it ends, enable autopay again to continue."
                ),
            )
        org.cancellation_effective = None
        await db.commit()
        await db.refresh(org)
        logger.info("cancellation_withdrawn", org_id=current_user.org_id)
        return _plan_info(
            org,
            await _current_cycle(db, org.id),
            await _org_wa_addon(db, org.id),
            await _latest_cycle(db, org.id),
        )

    cycle_end = await _latest_cycle_end(db, org.id)
    if org.razorpay_subscription_id:
        try:
            client = _get_client()
            await asyncio.to_thread(
                client.subscription.cancel,
                org.razorpay_subscription_id,
                {"cancel_at_cycle_end": bool(cycle_end and cycle_end > date.today())},
            )
        except Exception as exc:
            logger.error("autopay_cancel_failed", error=str(exc)[:160])
            raise HTTPException(
                status_code=502,
                detail="Razorpay could not schedule the cancellation",
            )
    if cycle_end and cycle_end > date.today():
        org.cancellation_effective = cycle_end
    else:
        # Nothing paid-for left to honour (trial / paused / already lapsed).
        org.status = "cancelled"
        org.cancellation_effective = None
    org.pending_plan = None
    org.pending_plan_effective = None
    await db.commit()
    await db.refresh(org)
    logger.info(
        "cancellation_scheduled",
        org_id=current_user.org_id,
        effective=org.cancellation_effective.isoformat() if org.cancellation_effective else "now",
    )
    return _plan_info(
        org,
        await _current_cycle(db, org.id),
        await _org_wa_addon(db, org.id),
        await _latest_cycle(db, org.id),
    )


class GstinBody(BaseModel):
    gstin: str = Field("", max_length=15)


_GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]$")


@router.post("/billing/gstin", response_model=PlanInfo)
async def set_gstin(
    body: GstinBody,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PlanInfo:
    """Save the clinic's GSTIN — printed on payment invoices for input credit.
    Empty string clears it."""
    if current_user.role != "org_admin":
        raise HTTPException(status_code=403, detail="Only a clinic owner can set the GSTIN")
    g = body.gstin.strip().upper()
    if g and not _GSTIN_RE.match(g):
        raise HTTPException(status_code=422, detail="That doesn't look like a valid 15-character GSTIN")
    org = await _load_my_org(current_user, db)
    org.gstin = g or None
    await db.commit()
    logger.info("gstin_saved", org_id=current_user.org_id, set=bool(g))
    return _plan_info(
        org,
        await _current_cycle(db, org.id),
        await _org_wa_addon(db, org.id),
        await _latest_cycle(db, org.id),
    )


@router.post(
    "/verify-payment",
    response_model=VerifyPaymentResponse,
    dependencies=[Depends(verify_payment_limit)],
)
async def verify_payment(
    request: Request,
    req: VerifyPaymentRequest,
    db: AsyncSession = Depends(get_db),
) -> VerifyPaymentResponse:
    """Verify HMAC-SHA256 signature: hex(HMAC(order_id|payment_id, KEY_SECRET)).

    Audit:
      - payment.verify.success on valid signature (resource_id=order_id)
      - payment.verify.fail on signature mismatch (success=False, resource_id=order_id)

    Even on 400 (signature mismatch), the audit row is written before raising.
    Audit failure is caught and logged — never re-raised.
    """
    # SEC #6: real proxy-aware client IP for the payment-verify audit record,
    # not the shared Cloudflare/Render socket peer.
    from backend.middleware.rate_limit import client_ip as _client_ip

    try:
        client_ip = _client_ip(request)
    except Exception:  # noqa: BLE001
        client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    # iter1 #5: derive org_id/plan from the TRUSTED server-created order, NOT
    # from client-supplied fields (forgeable on this unauthenticated route).
    trusted_notes = _trusted_order_notes(req.razorpay_order_id)
    org_id = _extract_org_id(trusted_notes or None)

    if not settings.razorpay_key_secret:
        raise HTTPException(status_code=500, detail="Razorpay credentials not configured")

    payload = f"{req.razorpay_order_id}|{req.razorpay_payment_id}".encode()
    expected = hmac.new(
        settings.razorpay_key_secret.encode(),
        payload,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, req.razorpay_signature):
        logger.warning(
            "razorpay_signature_mismatch",
            order_id=req.razorpay_order_id,
            payment_id=req.razorpay_payment_id,
        )
        # Audit the failure BEFORE raising — metadata has order_id but no PII
        try:
            await _audit_svc.write_audit_row(
                action="payment.verify.fail",
                resource_type="payment",
                resource_id=req.razorpay_order_id,
                org_id=org_id,
                ip_address=client_ip,
                user_agent=user_agent,
                metadata={"error": "signature_mismatch"},
                success=False,
            )
        except Exception as audit_err:
            logger.error("audit_write_failed", action="payment.verify.fail", error=str(audit_err))
        raise HTTPException(status_code=400, detail="Signature verification failed")

    logger.info(
        "razorpay_payment_verified",
        order_id=req.razorpay_order_id,
        payment_id=req.razorpay_payment_id,
    )

    # Audit successful verification — payment_id is not PII
    try:
        await _audit_svc.write_audit_row(
            action="payment.verify.success",
            resource_type="payment",
            resource_id=req.razorpay_order_id,
            org_id=org_id,
            ip_address=client_ip,
            user_agent=user_agent,
            metadata={"payment_id": req.razorpay_payment_id},
            success=True,
        )
    except Exception as audit_err:
        logger.error(
            "audit_write_failed", action="payment.verify.success", error=str(audit_err)
        )

    # #354: activate ON the verified signature — the HMAC only computes with
    # our key secret, so a valid signature IS proof of payment. The webhook
    # stays as the redundant backstop (activate_subscription is idempotent by
    # payment_id, so webhook redelivery after this is a no-op). Before this,
    # activation lived ONLY in the webhook — unconfigured dashboards meant n
    # successful checkouts produced ZERO cycles, no lock, no invoice.
    # A WhatsApp add-on order buys a FEATURE, not a billing cycle — running
    # activate_subscription on it would start a cycle nobody paid a plan for.
    if (trusted_notes or {}).get("kind") == "whatsapp_addon":
        try:
            await _enable_whatsapp_addon(db, trusted_notes, req.razorpay_payment_id)
        except Exception as e:  # noqa: BLE001 — money taken; never fail the
            # verified response. Support/webhook resolves it.
            logger.error("wa_addon_enable_failed", error=str(e)[:160])
    elif org_id is not None:
        try:
            plan_note = (trusted_notes.get("plan") or "").strip().lower() or None
            act = await activate_subscription(
                db, str(org_id), plan_note, req.razorpay_payment_id
            )
            logger.info("verify_activation", status=act, org_id=str(org_id))
        except Exception as e:  # noqa: BLE001 — money taken; never fail the
            # verified response. The webhook/backstop or support resolves it.
            logger.error("verify_activation_failed", error=str(e)[:160])
    else:
        logger.error("verify_activation_no_org", order_id=req.razorpay_order_id)

    return VerifyPaymentResponse(
        verified=True,
        payment_id=req.razorpay_payment_id,
        order_id=req.razorpay_order_id,
    )


# ── Subscription activation (authoritative, webhook-driven) ──────────────────


async def activate_subscription(
    db: AsyncSession, org_id_raw, plan: str | None, payment_id: str,
    *, billed_usage: bool = True,
) -> str:
    """Idempotently mark an org active and record a paid BillingCycle (TD-019).

    Idempotency key is razorpay_payment_id: a webhook redelivery (Razorpay
    retries until it gets a 2xx) must not double-bill or double-activate. Returns
    a short status string for logging. Never raises on a benign condition.
    """
    from backend.models.schema import BillingCycle, Organization

    try:
        org_uuid = _uuid.UUID(str(org_id_raw))
    except (ValueError, TypeError):
        return "bad_org_id"

    # Serialize deliveries for one provider payment before read/write.
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"razorpay:{payment_id}"},
    )

    # Idempotency: already processed this exact payment?
    seen = (
        await db.execute(
            select(BillingCycle).where(BillingCycle.razorpay_payment_id == payment_id)
        )
    ).scalar_one_or_none()
    if seen is not None:
        return "already_processed"

    org = (
        await db.execute(select(Organization).where(Organization.id == org_uuid))
    ).scalar_one_or_none()
    if org is None:
        logger.warning("activation_org_not_found", org_id=str(org_uuid))
        return "org_not_found"

    chosen_plan = plan if plan in PLANS else org.plan
    plan_def = PLANS.get(chosen_plan)
    if plan_def is None:
        return "bad_plan"

    now = datetime.now(timezone.utc)
    org.status = "active"
    org.plan = chosen_plan
    if org.subscription_started_at is None:
        org.subscription_started_at = now

    today = now.date()
    # Anniversary billing: the FIRST cycle starts the day they pay. A RENEWAL
    # paid early starts where the current cycle ends (no paid days lost); paid
    # late, it starts today (the gap wasn't served).
    last = (
        await db.execute(
            select(BillingCycle)
            .where(BillingCycle.org_id == org.id)
            .order_by(BillingCycle.cycle_end.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    start = last.cycle_end if (last is not None and last.cycle_end > today) else today
    used_closing = 0.0
    if last is not None:
        # Close out the ending cycle's meter (#341): its extra usage was billed
        # inside this payment (subscription_order_breakdown at order time).
        used_closing = await _cycle_minutes_used(db, org.id, last.cycle_start, last.cycle_end)
        last_plan = PLANS.get(last.plan)
        if last_plan is not None:
            over_min = max(0, int(round(used_closing)) - last_plan.included_minutes)
            last.minutes_used = int(round(used_closing))
            last.overage_minutes = over_min
            last.overage_amount = int(round(over_min * last_plan.overage_per_min))
            # The recurring plan charge contains fixed plan/add-on pricing.
            # Preserve extra usage as outstanding instead of falsely marking
            # it paid by a debit that did not include it.
            if not billed_usage and over_min:
                last.status = "invoiced"
    db.add(
        BillingCycle(
            org_id=org.id,
            cycle_start=start,
            cycle_end=add_month(start),
            plan=chosen_plan,
            # #391: record the base actually charged (launch-offer aware).
            base_amount=effective_price(chosen_plan, org.subscription_started_at)[0],
            included_minutes=plan_def.included_minutes,
            minutes_used=0,
            overage_minutes=0,
            overage_rate=int(plan_def.overage_per_min),
            overage_amount=0,
            status="paid",
            razorpay_payment_id=payment_id,
        )
    )
    await db.commit()
    logger.info("subscription_activated", org_id=str(org.id), plan=chosen_plan)

    # #342: mail the clinic a detailed invoice/receipt (the SAME numbers the
    # order charged). Best-effort — RULE 8, never un-activates a paid org.
    try:
        from backend.services.billing_math import subscription_order_breakdown
        from backend.services.invoice_email import send_payment_invoice

        bd = subscription_order_breakdown(
            chosen_plan,
            used_closing if billed_usage else 0,
            int(getattr(org, "minutes_adjustment", 0) or 0),
            subscription_started_at=org.subscription_started_at,
            # The receipt must show the SAME numbers the order charged.
            whatsapp_addon=await _org_wa_addon(db, org.id),
        )
        await send_payment_invoice(
            to_email=org.owner_email or "", org_name=org.name,
            org_gstin=getattr(org, "gstin", None), plan=chosen_plan,
            cycle_start=start, cycle_end=add_month(start),
            bd=bd, payment_id=payment_id,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("invoice_send_failed", error=str(e)[:120])
    return "activated"


@router.post(
    "/razorpay-webhook",
    dependencies=[Depends(razorpay_webhook_limit)],
)
async def razorpay_webhook(
    request: Request, db: AsyncSession = Depends(get_db)
) -> dict:
    """Authoritative subscription activation (TD-019/G2).

    Razorpay POSTs here on payment events. We verify the webhook signature over
    the RAW body (the signature is the auth — no JWT), then on a success event
    activate the org named in the order's server-set ``notes``. Always answers
    200 once the signature is valid so Razorpay stops retrying; a bad signature
    is 400.
    """
    raw = await request.body()
    secret = settings.razorpay_webhook_secret
    if not secret:
        logger.error("razorpay_webhook_secret_unset")
        raise HTTPException(status_code=500, detail="Webhook not configured")

    sent_sig = request.headers.get("X-Razorpay-Signature", "")
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sent_sig):
        logger.warning("razorpay_webhook_bad_signature")
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    import json as _json

    try:
        body = _json.loads(raw.decode() or "{}")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid webhook body")

    event = body.get("event", "")
    payload = body.get("payload", {}) or {}
    order_ent = (payload.get("order") or {}).get("entity", {}) or {}
    payment_ent = (payload.get("payment") or {}).get("entity", {}) or {}
    subscription_ent = (payload.get("subscription") or {}).get("entity", {}) or {}

    if event.startswith("subscription."):
        sub_id = subscription_ent.get("id")
        sub_notes = subscription_ent.get("notes") or {}
        org_id = _extract_org_id(sub_notes)
        if not sub_id or org_id is None:
            logger.warning("razorpay_subscription_webhook_unattributed", wh_event=event)
            return {"status": "ignored", "event": event}
        org = (
            await db.execute(select(Organization).where(Organization.id == org_id))
        ).scalar_one_or_none()
        if org is None:
            return {"status": "org_not_found"}
        if org.razorpay_subscription_id not in {None, sub_id}:
            logger.error(
                "razorpay_subscription_id_conflict",
                org_id=str(org.id), incoming=sub_id,
            )
            return {"status": "subscription_conflict"}

        state = event.removeprefix("subscription.")
        org.razorpay_subscription_id = sub_id
        org.razorpay_subscription_status = (
            subscription_ent.get("status") or state
        )
        org.razorpay_customer_id = (
            subscription_ent.get("customer_id") or org.razorpay_customer_id
        )
        if state == "halted":
            org.status = "paused"
        elif state in {"cancelled", "completed", "expired"}:
            org.status = "cancelled"
            org.cancellation_effective = None

        payment_id = payment_ent.get("id")
        if state == "charged" and payment_id:
            charged_plan = sub_notes.get("plan")
            if (
                org.pending_plan in PLANS
                and org.pending_plan_effective
                and org.pending_plan_effective <= date.today()
            ):
                charged_plan = org.pending_plan
            result = await activate_subscription(
                db, org.id, charged_plan, payment_id,
                billed_usage=False,
            )
            if result == "activated" and charged_plan == org.pending_plan:
                org.pending_plan = None
                org.pending_plan_effective = None
                await db.commit()
        else:
            await db.commit()
            result = state
        logger.info(
            "razorpay_subscription_webhook_processed",
            wh_event=event, result=result, org_id=str(org.id),
        )
        return {"status": result}

    notes = order_ent.get("notes") or payment_ent.get("notes") or {}
    payment_id = payment_ent.get("id") or order_ent.get("id")

    # Only success events activate. Anything else is acknowledged and ignored.
    if event not in ("order.paid", "payment.captured") or not payment_id:
        logger.info("razorpay_webhook_ignored", wh_event=event)
        return {"status": "ignored", "event": event}

    if notes.get("kind") == "whatsapp_addon":
        # Checkout may succeed after the browser closes. The signed webhook is
        # therefore an authoritative add-on activation path, not a plan cycle.
        status = await _enable_whatsapp_addon(db, notes, payment_id)
    else:
        status = await activate_subscription(
            db, notes.get("org_id"), notes.get("plan"), payment_id
        )
    logger.info("razorpay_webhook_processed", wh_event=event, result=status)
    return {"status": status}

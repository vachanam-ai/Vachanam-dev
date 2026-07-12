"""
Razorpay Standard Web Checkout integration.

Endpoints:
- POST /api/create-order   — create a Razorpay order (amount in paise, min 100)
- POST /api/verify-payment — verify HMAC-SHA256 signature after checkout

Key secret never leaves the server. Frontend receives only razorpay_key_id (public).
"""
import hashlib
import hmac
import uuid as _uuid
from datetime import date, datetime, timedelta, timezone

import razorpay
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
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
from backend.services.billing_math import PLANS

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


def _trusted_org_id_for_order(order_id: str) -> _uuid.UUID | None:
    """Resolve the org_id for audit attribution from the TRUSTED Razorpay order.

    iter1 #5: /verify-payment is unauthenticated (the HMAC signature is the auth),
    so it must NOT attribute the audit row to a client-supplied notes.org_id — a
    caller could forge `notes` to mis-attribute (or hide) a verification. The order
    was created server-side with notes.org_id = current_user.org_id (see
    create_order), so we fetch the order back from Razorpay and read ITS notes.
    Best-effort: any failure (creds unset, network, unknown order) → None, never
    raises; org_id is attribution metadata, not a gate on the signature check.
    """
    if not order_id:
        return None
    try:
        client = _get_client()
        order = client.order.fetch(order_id)
    except Exception as e:  # noqa: BLE001 — attribution is best-effort
        logger.warning("razorpay_order_fetch_failed", order_id=order_id, error=str(e))
        return None
    return _extract_org_id(order.get("notes") if isinstance(order, dict) else None)


def _get_client() -> razorpay.Client:
    if not settings.razorpay_key_id or not settings.razorpay_key_secret:
        raise HTTPException(status_code=500, detail="Razorpay credentials not configured")
    return razorpay.Client(auth=(settings.razorpay_key_id, settings.razorpay_key_secret))


class CreateOrderRequest(BaseModel):
    # The amount is NEVER client-controlled (TD-025/G1): a subscription order is
    # for a fixed plan price, derived server-side. The client only names the plan.
    plan: str = Field(..., description="solo | clinic | multi")


class CreateOrderResponse(BaseModel):
    order_id: str
    amount: int
    currency: str
    key_id: str


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
) -> CreateOrderResponse:
    """Create a Razorpay subscription order for the caller's org.

    Auth-gated (TD-025/G1): only a clinic owner with an org can subscribe. The
    amount is the plan's fixed price (server-derived, not client-supplied), and
    the order's ``notes`` carry org_id + plan set BY US — so the webhook can
    trust them when it activates the subscription.
    """
    if current_user.role != "org_admin" or not current_user.org_id:
        raise HTTPException(status_code=403, detail="Only a clinic owner can subscribe")

    plan = req.plan.strip().lower()
    plan_def = PLANS.get(plan)
    if plan_def is None:
        raise HTTPException(status_code=422, detail="plan must be solo, clinic or multi")

    amount_paise = plan_def.base_rupees * 100
    client = _get_client()
    payload = {
        "amount": amount_paise,
        "currency": "INR",
        "receipt": f"sub_{plan}_{_uuid.uuid4().hex[:10]}",
        # notes set SERVER-SIDE — these are what the webhook trusts for activation
        "notes": {"org_id": current_user.org_id, "plan": plan},
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


async def _latest_cycle_end(db: AsyncSession, org_id) -> date | None:
    from backend.models.schema import BillingCycle

    return (
        await db.execute(
            select(BillingCycle.cycle_end)
            .where(BillingCycle.org_id == org_id)
            .order_by(BillingCycle.cycle_end.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


def _plan_info(org: Organization, cycle_end: date | None = None) -> "PlanInfo":
    return PlanInfo(
        plan=org.plan,
        status=org.status,
        pending_plan=org.pending_plan,
        pending_plan_effective=(
            org.pending_plan_effective.isoformat() if org.pending_plan_effective else None
        ),
        cycle_end=cycle_end.isoformat() if cycle_end else None,
    )


@router.get("/plan", response_model=PlanInfo)
async def get_plan(
    current_user: CurrentUser = Depends(get_current_user),
    db: "AsyncSession" = Depends(get_db),
) -> "PlanInfo":
    """Caller's current plan + any scheduled change + current cycle end."""
    org = await _load_my_org(current_user, db)
    return _plan_info(org, await _latest_cycle_end(db, org.id))


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
    if plan not in PLANS:
        raise HTTPException(status_code=422, detail="plan must be solo, clinic or multi")

    org = await _load_my_org(current_user, db)
    if plan == org.plan:
        # No-op / cancel a previously scheduled change.
        org.pending_plan = None
        org.pending_plan_effective = None
    else:
        cycle_end = await _latest_cycle_end(db, org.id)
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
    return _plan_info(org)


@router.post(
    "/verify-payment",
    response_model=VerifyPaymentResponse,
    dependencies=[Depends(verify_payment_limit)],
)
async def verify_payment(request: Request, req: VerifyPaymentRequest) -> VerifyPaymentResponse:
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
    # iter1 #5: derive org_id from the TRUSTED server-created order, NOT from the
    # client-supplied req.notes (which is forgeable on this unauthenticated route).
    org_id = _trusted_org_id_for_order(req.razorpay_order_id)

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

    return VerifyPaymentResponse(
        verified=True,
        payment_id=req.razorpay_payment_id,
        order_id=req.razorpay_order_id,
    )


# ── Subscription activation (authoritative, webhook-driven) ──────────────────


async def activate_subscription(
    db: AsyncSession, org_id_raw, plan: str | None, payment_id: str
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
    last_end = (
        await db.execute(
            select(BillingCycle.cycle_end)
            .where(BillingCycle.org_id == org.id)
            .order_by(BillingCycle.cycle_end.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    start = last_end if (last_end and last_end > today) else today
    db.add(
        BillingCycle(
            org_id=org.id,
            cycle_start=start,
            cycle_end=start + timedelta(days=30),
            plan=chosen_plan,
            base_amount=plan_def.base_rupees,
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
    notes = order_ent.get("notes") or payment_ent.get("notes") or {}
    payment_id = payment_ent.get("id") or order_ent.get("id")

    # Only success events activate. Anything else is acknowledged and ignored.
    if event not in ("order.paid", "payment.captured") or not payment_id:
        logger.info("razorpay_webhook_ignored", wh_event=event)
        return {"status": "ignored", "event": event}

    status = await activate_subscription(
        db, notes.get("org_id"), notes.get("plan"), payment_id
    )
    logger.info("razorpay_webhook_processed", wh_event=event, result=status)
    return {"status": status}

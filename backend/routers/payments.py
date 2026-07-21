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
import uuid as _uuid
from datetime import date, datetime, timedelta, timezone

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
from backend.services.billing_math import PLANS, effective_price, subscription_order_breakdown

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
    plan: str = Field(..., description="lite | solo | clinic | multi")


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


async def _latest_cycle_end(db: AsyncSession, org_id) -> date | None:
    last = await _latest_cycle(db, org_id)
    return last.cycle_end if last else None


def _plan_info(org: Organization, last_cycle=None) -> "PlanInfo":
    _base, _is_offer = effective_price(org.plan, org.subscription_started_at)
    return PlanInfo(
        next_base_rupees=_base,
        is_offer=_is_offer,
        plan=org.plan,
        status=org.status,
        pending_plan=org.pending_plan,
        pending_plan_effective=(
            org.pending_plan_effective.isoformat() if org.pending_plan_effective else None
        ),
        cycle_end=last_cycle.cycle_end.isoformat() if last_cycle else None,
        # The cycle row is created the moment the webhook confirms payment —
        # its created_at IS the payment timestamp (#353 "last payment date").
        last_payment_date=(
            last_cycle.created_at.date().isoformat()
            if last_cycle is not None and last_cycle.created_at
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
    return _plan_info(org, await _latest_cycle(db, org.id))


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
        raise HTTPException(status_code=422, detail="plan must be lite, solo, clinic or multi")

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
    return _plan_info(org, await _latest_cycle(db, org.id))


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
    if org_id is not None:
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
    db.add(
        BillingCycle(
            org_id=org.id,
            cycle_start=start,
            cycle_end=start + timedelta(days=30),
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
            chosen_plan, used_closing, int(getattr(org, "minutes_adjustment", 0) or 0),
            subscription_started_at=org.subscription_started_at,
        )
        await send_payment_invoice(
            to_email=org.owner_email or "", org_name=org.name,
            org_gstin=getattr(org, "gstin", None), plan=chosen_plan,
            cycle_start=start, cycle_end=start + timedelta(days=30),
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

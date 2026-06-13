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

import razorpay
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

import backend.services.audit_service as _audit_svc
from backend.config import settings
from backend.middleware.rate_limit import create_order_limit, verify_payment_limit

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


def _get_client() -> razorpay.Client:
    if not settings.razorpay_key_id or not settings.razorpay_key_secret:
        raise HTTPException(status_code=500, detail="Razorpay credentials not configured")
    return razorpay.Client(auth=(settings.razorpay_key_id, settings.razorpay_key_secret))


class CreateOrderRequest(BaseModel):
    amount: int = Field(..., ge=100, description="Amount in paise (minimum 100 = ₹1)")
    currency: str = Field(default="INR", max_length=3)
    receipt: str | None = Field(default=None, max_length=40)
    notes: dict | None = None


class CreateOrderResponse(BaseModel):
    order_id: str
    amount: int
    currency: str
    key_id: str


class VerifyPaymentRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str
    notes: dict | None = None  # optional — pass org_id here for audit attribution


class VerifyPaymentResponse(BaseModel):
    verified: bool
    payment_id: str
    order_id: str


@router.post(
    "/create-order",
    response_model=CreateOrderResponse,
    dependencies=[Depends(create_order_limit)],
)
async def create_order(request: Request, req: CreateOrderRequest) -> CreateOrderResponse:
    """Create a Razorpay order. amount is in paise (₹1 = 100 paise)."""
    client = _get_client()
    payload = {
        "amount": req.amount,
        "currency": req.currency,
        "receipt": req.receipt or f"rcpt_{req.amount}",
    }
    if req.notes:
        payload["notes"] = req.notes

    try:
        order = client.order.create(payload)
    except razorpay.errors.BadRequestError as e:
        # G12: log the detail, return a generic message — the raw provider error
        # can carry internal IDs/config hints.
        logger.error("razorpay_order_bad_request", error=str(e), amount=req.amount)
        raise HTTPException(status_code=400, detail="Order rejected by payment provider")
    except razorpay.errors.SignatureVerificationError as e:
        logger.error("razorpay_auth_failed", error=str(e))
        raise HTTPException(status_code=401, detail="Razorpay auth failed")
    except Exception as e:
        logger.error("razorpay_order_create_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Order creation failed")

    logger.info("razorpay_order_created", order_id=order["id"], amount=req.amount)
    return CreateOrderResponse(
        order_id=order["id"],
        amount=order["amount"],
        currency=order["currency"],
        key_id=settings.razorpay_key_id,
    )


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
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    org_id = _extract_org_id(req.notes)

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

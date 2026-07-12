"""Payment invoice/receipt email — sent to the clinic owner the moment the
Razorpay webhook confirms a subscription payment (#342).

Until VACHANAM_GSTIN is set (registration pending) the document is titled
"Payment receipt" and says a GST tax invoice will follow; once set it is
titled "Tax invoice" and carries both GSTINs (ours + the clinic's, when the
owner has saved theirs in Settings — needed for their input-tax credit).

RULE 8: best-effort — a Resend outage logs and returns, it never blocks or
rolls back an activation.
"""
from __future__ import annotations

from datetime import date

import httpx
import structlog

from backend.config import settings

logger = structlog.get_logger()


def invoice_number(cycle_start: date, payment_id: str) -> str:
    """Traceable, unique, human-readable. NOT a statutory consecutive serial —
    switch to a DB sequence when GST registration lands (noted in TECH_DEBT)."""
    tail = "".join(c for c in payment_id if c.isalnum())[-6:].upper()
    return f"VAC-{cycle_start:%Y%m%d}-{tail}"


def build_invoice_text(
    *, org_name: str, org_gstin: str | None, plan: str, cycle_start: date,
    cycle_end: date, bd: dict, payment_id: str,
) -> tuple[str, str]:
    """(subject, body) for the payment mail. `bd` is
    billing_math.subscription_order_breakdown output — the SAME numbers the
    Razorpay order charged."""
    ours = settings.vachanam_gstin.strip()
    doc = "Tax invoice" if ours else "Payment receipt"
    no = invoice_number(cycle_start, payment_id)
    plan_label = {"solo": "Starter", "clinic": "Clinic", "multi": "Multi"}.get(plan, plan)

    lines = [
        f"{doc}  ·  {no}",
        f"Date: {date.today():%d %b %Y}",
        "",
        "From: Vachanam, Hyderabad, India",
        (f"GSTIN: {ours}" if ours
         else "GST registration in progress — a GST tax invoice will follow."),
        f"To: {org_name}" + (f" (GSTIN: {org_gstin})" if org_gstin else ""),
        "",
        f"Plan: {plan_label}  ·  Service period: "
        f"{cycle_start:%d %b %Y} to {cycle_end:%d %b %Y}",
        "",
        f"  Subscription (base)                 Rs {bd['base']:>12,.2f}",
    ]
    if bd["overage_minutes"]:
        lines.append(
            f"  Extra usage: {bd['overage_minutes']} min x Rs 5/min"
            f"{'':<6} Rs {bd['overage_amount']:>12,.2f}"
        )
    subtotal = bd["base"] + bd["overage_amount"]
    lines += [
        f"  Subtotal                            Rs {subtotal:>12,.2f}",
        f"  GST @ 18%                           Rs {bd['gst']:>12,.2f}",
        f"  TOTAL PAID                          Rs {bd['total']:>12,.2f}",
        "",
        f"Payment ID: {payment_id} (Razorpay)",
        "Your service is active for the full period above. Extra usage beyond "
        "your plan's included minutes is billed at Rs 5/min with your next "
        "renewal.",
        "",
        "Add or update your clinic's GSTIN any time in Settings -> Plan & "
        "billing to have it printed here for input-tax credit.",
        "",
        "Questions? Reply to this email or write to hello@vachanam.in.",
        "— Vachanam · Healing starts with being heard.",
    ]
    return f"{doc} {no} — Vachanam {plan_label} plan", "\n".join(lines)


async def send_payment_invoice(
    *, to_email: str, org_name: str, org_gstin: str | None, plan: str,
    cycle_start: date, cycle_end: date, bd: dict, payment_id: str,
) -> None:
    if not settings.resend_api_key or not to_email:
        return
    subject, text = build_invoice_text(
        org_name=org_name, org_gstin=org_gstin, plan=plan,
        cycle_start=cycle_start, cycle_end=cycle_end, bd=bd, payment_id=payment_id,
    )
    from backend.services.resilience import guard

    async def _post():
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {settings.resend_api_key}"},
                json={"from": settings.resend_from, "to": [to_email],
                      "subject": subject, "text": text},
            )
            r.raise_for_status()

    result = await guard("resend_email", _post, timeout=12, retries=1, fallback=False)
    if result is False:
        logger.warning("invoice_email_failed", to_last4=to_email[-4:])
    else:
        logger.info("invoice_email_sent", payment_id=payment_id)

"""Payment receipt email — sent the moment a subscription payment is
confirmed (#342, #354). Restyled after Stripe's receipt mail (#358, Vinay):
a clean HTML card (big amount, paid date, receipt number, line items) plus a
matching one-page PDF attachment. GSTIN blocks removed on Vinay's call
("complicates things") — the GST 18% line item stays because the price
charges it; statutory tax-invoice formatting returns with TD-038 when GST
registration lands.

RULE 8: best-effort — a Resend outage logs and returns, it never blocks or
rolls back an activation.
"""
from __future__ import annotations

from datetime import date
from html import escape

import httpx
import structlog

from backend.config import settings

logger = structlog.get_logger()

_PLAN_LABEL = {"lite": "Lite", "solo": "Starter", "clinic": "Clinic", "multi": "Multi"}


def invoice_number(cycle_start: date, payment_id: str) -> str:
    """Traceable, unique, human-readable receipt number. NOT a statutory
    consecutive serial — switch to a DB sequence when GST registration lands
    (TD-038)."""
    tail = "".join(c for c in payment_id if c.isalnum())[-6:].upper()
    return f"VAC-{cycle_start:%Y%m%d}-{tail}"


def _rows(plan: str, bd: dict) -> list[tuple[str, float]]:
    rows = [(f"{_PLAN_LABEL.get(plan, plan)} plan", float(bd["base"]))]
    if bd["overage_minutes"]:
        rows.append(
            (f"Extra usage · {bd['overage_minutes']} min × Rs 5/min",
             float(bd["overage_amount"]))
        )
    return rows


def build_invoice_text(
    *, org_name: str, org_gstin: str | None = None, plan: str, cycle_start: date,
    cycle_end: date, bd: dict, payment_id: str,
) -> tuple[str, str]:
    """(subject, plain-text body) — the fallback for clients that block HTML.
    `bd` is billing_math.subscription_order_breakdown output — the SAME
    numbers the Razorpay order charged. org_gstin accepted for call-site
    compatibility, deliberately unused (#358)."""
    no = invoice_number(cycle_start, payment_id)
    subtotal = bd["base"] + bd["overage_amount"]
    lines = [
        f"Receipt from Vachanam  ·  {no}",
        f"Rs {bd['total']:,.2f} paid on {date.today():%d %b %Y}",
        "",
        f"Billed to: {org_name}",
        f"Service period: {cycle_start:%d %b %Y} to {cycle_end:%d %b %Y}",
        "",
    ]
    for label, amount in _rows(plan, bd):
        lines.append(f"  {label:<40} Rs {amount:>12,.2f}")
    lines.append(f"  {'Subtotal':<40} Rs {subtotal:>12,.2f}")
    if bd["gst"]:
        lines.append(f"  {'GST - India (18%)':<40} Rs {bd['gst']:>12,.2f}")
    lines += [
        f"  {'Amount paid':<40} Rs {bd['total']:>12,.2f}",
        "",
        f"Payment ID: {payment_id} (Razorpay)",
        "Your service is active for the full period above.",
        "",
        "Questions? Reply to this email or write to hello@vachanam.in.",
        "— Vachanam · Healing starts with being heard.",
    ]
    return (
        f"Your receipt from Vachanam · {no}",
        "\n".join(lines),
    )


def build_invoice_html(
    *, org_name: str, plan: str, cycle_start: date, cycle_end: date,
    bd: dict, payment_id: str,
) -> str:
    """Stripe-style receipt card (#358): big amount, paid date, receipt
    number, service period, line items, GST, amount paid. Inline styles only
    (email clients)."""
    no = invoice_number(cycle_start, payment_id)
    subtotal = bd["base"] + bd["overage_amount"]
    safe_org_name = escape(org_name, quote=True)
    safe_payment_id = escape(payment_id, quote=True)

    def money(v: float) -> str:
        return f"&#8377;{v:,.2f}"  # ₹ entity — HTML mail renders it fine

    item_rows = "".join(
        f'<tr><td style="padding:8px 0;color:#1a2024;">{label}</td>'
        f'<td style="padding:8px 0;text-align:right;color:#1a2024;">{money(amount)}</td></tr>'
        for label, amount in _rows(plan, bd)
    )
    gst_row = ""
    if bd["gst"]:
        gst_row = (
            '<tr><td style="padding:8px 0;color:#64747c;">GST &middot; India (18%)</td>'
            f'<td style="padding:8px 0;text-align:right;color:#64747c;">{money(bd["gst"])}</td></tr>'
        )
    return f"""\
<div style="background:#f2f4f4;padding:32px 12px;font-family:Helvetica,Arial,sans-serif;">
  <div style="max-width:520px;margin:0 auto;">
    <p style="text-align:center;font-size:20px;font-weight:bold;color:#0e4a49;margin:0 0 20px;">Vachanam</p>
    <div style="background:#ffffff;border-radius:12px;padding:28px 28px 22px;box-shadow:0 1px 4px rgba(0,0,0,0.08);">
      <p style="margin:0;color:#64747c;font-size:14px;">Receipt from Vachanam</p>
      <p style="margin:6px 0 2px;font-size:32px;font-weight:bold;color:#1a2024;">{money(bd['total'])}</p>
      <p style="margin:0 0 18px;color:#64747c;font-size:13px;">Paid {date.today():%B %d, %Y}</p>
      <table style="width:100%;font-size:13px;border-collapse:collapse;margin-bottom:6px;">
        <tr><td style="padding:4px 0;color:#64747c;">Receipt number</td>
            <td style="padding:4px 0;text-align:right;color:#1a2024;">{no}</td></tr>
        <tr><td style="padding:4px 0;color:#64747c;">Payment ID</td>
            <td style="padding:4px 0;text-align:right;color:#1a2024;">{safe_payment_id}</td></tr>
        <tr><td style="padding:4px 0;color:#64747c;">Billed to</td>
            <td style="padding:4px 0;text-align:right;color:#1a2024;">{safe_org_name}</td></tr>
      </table>
    </div>
    <div style="background:#ffffff;border-radius:12px;padding:24px 28px;margin-top:16px;box-shadow:0 1px 4px rgba(0,0,0,0.08);">
      <p style="margin:0 0 4px;font-weight:bold;color:#1a2024;font-size:15px;">Receipt {no}</p>
      <p style="margin:0 0 14px;color:#64747c;font-size:13px;">{cycle_start:%b %d} &ndash; {cycle_end:%b %d, %Y}</p>
      <table style="width:100%;font-size:14px;border-collapse:collapse;">
        {item_rows}
        <tr><td colspan="2" style="border-top:1px solid #e6eaea;padding:0;"></td></tr>
        <tr><td style="padding:8px 0;color:#64747c;">Subtotal</td>
            <td style="padding:8px 0;text-align:right;color:#1a2024;">{money(subtotal)}</td></tr>
        {gst_row}
        <tr><td colspan="2" style="border-top:1px solid #e6eaea;padding:0;"></td></tr>
        <tr><td style="padding:10px 0;font-weight:bold;color:#1a2024;">Amount paid</td>
            <td style="padding:10px 0;text-align:right;font-weight:bold;color:#1a2024;">{money(bd['total'])}</td></tr>
      </table>
      <p style="margin:14px 0 0;color:#64747c;font-size:12px;">
        Your service is active for the full period above.
        Questions? Write to <a href="mailto:hello@vachanam.in" style="color:#0e4a49;">hello@vachanam.in</a>.
      </p>
    </div>
    <p style="text-align:center;color:#9aa7ad;font-size:11px;margin:18px 0 0;">
      Vachanam &middot; Healing starts with being heard.
    </p>
  </div>
</div>"""


def build_invoice_pdf(
    *, org_name: str, org_gstin: str | None = None, plan: str, cycle_start: date,
    cycle_end: date, bd: dict, payment_id: str,
) -> bytes:
    """One-page PDF receipt matching the mail card (#357/#358). Pure-Python
    fpdf2, core Helvetica (amounts say "Rs" — the rupee glyph would need an
    embedded TTF). org_gstin accepted for compatibility, unused (#358)."""
    from fpdf import FPDF

    no = invoice_number(cycle_start, payment_id)
    subtotal = bd["base"] + bd["overage_amount"]

    TEAL = (14, 74, 73)
    INK = (26, 32, 36)
    SLATE = (100, 116, 124)

    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_left_margin(14)
    pdf.add_page()

    # Header band
    pdf.set_fill_color(*TEAL)
    pdf.rect(0, 0, 210, 26, style="F")
    pdf.set_xy(14, 7)
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(100, 12, "Vachanam")
    pdf.set_xy(110, 7)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(86, 12, "RECEIPT", align="R")

    # Big amount + paid date
    pdf.set_xy(14, 36)
    pdf.set_font("Helvetica", "B", 24)
    pdf.set_text_color(*INK)
    pdf.cell(0, 12, f"Rs {bd['total']:,.2f}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(*SLATE)
    pdf.cell(0, 7, f"Paid {date.today():%B %d, %Y}", new_x="LMARGIN", new_y="NEXT")

    # Meta rows
    pdf.ln(4)
    pdf.set_font("Helvetica", "", 10)
    for label, value in (
        ("Receipt number", no),
        ("Payment ID", f"{payment_id} (Razorpay)"),
        ("Billed to", org_name),
        ("Service period", f"{cycle_start:%d %b %Y} to {cycle_end:%d %b %Y}"),
    ):
        pdf.set_text_color(*SLATE)
        pdf.cell(60, 7, label)
        pdf.set_text_color(*INK)
        pdf.cell(0, 7, value, new_x="LMARGIN", new_y="NEXT")

    # Line items
    def _row(label: str, amount: float, *, bold=False, fill=False, muted=False):
        pdf.set_font("Helvetica", "B" if bold else "", 10)
        pdf.set_text_color(*(SLATE if muted else INK))
        if fill:
            pdf.set_fill_color(232, 242, 241)
        pdf.set_x(14)
        pdf.cell(132, 8, label, border="B", fill=fill)
        pdf.cell(50, 8, f"Rs {amount:,.2f}", border="B", align="R", fill=fill,
                 new_x="LMARGIN", new_y="NEXT")

    pdf.ln(4)
    for label, amount in _rows(plan, bd):
        _row(label.replace("×", "x").replace("·", "-"), amount)
    _row("Subtotal", subtotal)
    if bd["gst"]:
        _row("GST - India (18%)", bd["gst"], muted=True)
    _row("Amount paid", bd["total"], bold=True, fill=True)

    # Footer
    pdf.ln(6)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*SLATE)
    pdf.multi_cell(
        182, 5,
        "Your service is active for the full period above.\n"
        "Questions? Write to hello@vachanam.in\n"
        "Vachanam - Healing starts with being heard.",
    )
    return bytes(pdf.output())


async def send_payment_invoice(
    *, to_email: str, org_name: str, org_gstin: str | None = None, plan: str,
    cycle_start: date, cycle_end: date, bd: dict, payment_id: str,
) -> None:
    if not settings.resend_api_key or not to_email:
        return
    subject, text = build_invoice_text(
        org_name=org_name, plan=plan,
        cycle_start=cycle_start, cycle_end=cycle_end, bd=bd, payment_id=payment_id,
    )
    payload: dict = {"from": settings.resend_from, "to": [to_email],
                     "subject": subject, "text": text}
    # #358: Stripe-style HTML card; text remains the fallback body.
    try:
        payload["html"] = build_invoice_html(
            org_name=org_name, plan=plan, cycle_start=cycle_start,
            cycle_end=cycle_end, bd=bd, payment_id=payment_id,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("invoice_html_build_failed", error=str(e)[:120])
    # #357: PDF attachment. Build failure degrades to mail-only — a render
    # bug must never cost the clinic their receipt.
    try:
        import base64

        pdf_bytes = build_invoice_pdf(
            org_name=org_name, plan=plan, cycle_start=cycle_start,
            cycle_end=cycle_end, bd=bd, payment_id=payment_id,
        )
        payload["attachments"] = [{
            "filename": f"{invoice_number(cycle_start, payment_id)}.pdf",
            "content": base64.b64encode(pdf_bytes).decode(),
        }]
    except Exception as e:  # noqa: BLE001
        logger.warning("invoice_pdf_build_failed", error=str(e)[:120])

    from backend.services.resilience import guard

    async def _post():
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {settings.resend_api_key}"},
                json=payload,
            )
            r.raise_for_status()

    result = await guard("resend_email", _post, timeout=12, retries=1, fallback=False)
    if result is False:
        logger.warning("invoice_email_failed", to_last4=to_email[-4:])
    else:
        logger.info("invoice_email_sent", payment_id=payment_id)

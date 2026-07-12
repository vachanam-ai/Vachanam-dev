# Demo Leads (phone-first) — Design

**Date:** 2026-07-12 · **Approved by:** Vinay (option pick: "Leads tab on ticket rails")
**Trigger:** "booking demo should take clinics number and name and message. support
ticket should be of different format… new clients should be handled differently."

## Decision

Demo requests are **leads**, not support tickets — but they ride the existing
support_tickets rails (smallest diff, same SLA machinery). A separate leads
table / mini-CRM (option B) is deferred until inbound volume justifies it; the
data collected now (phone, clinic, message) migrates cleanly if we graduate.

## What was built

1. **Schema** — `support_tickets.phone` VARCHAR(20) NULL (migration `ab25`,
   additive; applied to prod before code deploy).
2. **API** — `POST /support/contact`:
   - `category=sales_demo` → phone REQUIRED (10-digit, digits extracted
     server-side), email optional, priority forced `high`, SLA 8h.
   - any other category → email required as before.
   - `GET /support/admin/tickets`: `leads=true` returns ONLY sales_demo;
     default inbox now EXCLUDES sales_demo (hard separation).
3. **Public /help** — two forms:
   - **Book a free demo** (teal-bordered, first): clinic name, your name,
     10-digit phone (client-validated), optional message. Subject composed as
     `Demo request — {clinic}`. Success copy: "we'll call you within a working
     day."
   - **Other questions**: name, email, subject, body, category (no sales_demo
     option — demos only via the demo form).
4. **Support dashboard** — Inbox | 🔥 Leads tab toggle. Lead cards show
   contact name + click-to-call phone; thread header shows phone for staff.

## Error handling

Anonymous forms still pass Turnstile (#336). Phone validation 422s with a
clear message. RULE 8: team email on new lead is best-effort.

## Tests

tests/integration/test_demo_leads.py (4): lead w/o email → high priority +
phone stored; short/missing phone 422; non-demo still requires email;
inbox/leads separation incl. phone in admin row.
tests/security/test_support_admin.py lead test updated to new contract.

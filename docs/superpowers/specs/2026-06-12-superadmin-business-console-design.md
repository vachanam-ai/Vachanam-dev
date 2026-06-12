# Super-Admin Business Console — Design (2026-06-12)

Requirements source: Vinay's message 2026-06-12 (verbatim scope, treated as approved).

## Goal
Platform owner (super_admin) sees the BUSINESS of Vachanam: every clinic's plan,
usage, limits, revenue, expense, profit, payments, growth — and can act:
pause/resume service, change plan, hard-block on minute exhaustion.

## DPDP boundary
Org-level commercial data ONLY. No patient names/phones ever cross this console.
Minutes/bookings are aggregates from call_logs (already last-4-only).

## Approach (chosen over alternatives)
- A (chosen): live computation from call_logs + orgs + pricing constants.
  Simple, correct at current scale (indexed branch_id+started_at).
- B (rejected): materialized usage tables + job — premature at <50 clinics.
- C (rejected): full invoice/billing service — Razorpay wiring is a later phase;
  BillingCycle rows render as "payments" when they exist.

## Money math (backend/services/billing_math.py, pure + unit-tested)
- PLANS: solo ₹1,999 / 100 min incl / ₹3 overage; clinic ₹7,999 / 2,100 / ₹3;
  multi ₹16,999 / 4,200 / ₹2.50 (CLAUDE.md pricing, final).
- Revenue (month) = base + overage_minutes x rate — ACTIVE orgs only
  (trial/paused/cancelled = ₹0 revenue).
- Expense (month) = minutes_used x ₹1.49 + DID_count x ₹1,000 (DIDs cost while held).
- Profit = revenue − expense.

## Backend (routers/admin.py, all require_admin)
- GET /admin/overview →
  - totals: clients + new-this-month + MoM growth %, minutes this month + MoM %,
    minutes all-time, revenue/expense/profit this month, calls today,
    voice bookings this month
  - clients[]: name, plan, status, owner phone/email, branches, DIDs,
    minutes used/included/left/pct, approaching (>=80%), exhausted, hard_block,
    revenue/expense/profit (month), calls + voice-bookings (month), trial days left
  - monthly[]: last 6 months {month, minutes, revenue, expense, new_clients}
  - payments[]: latest BillingCycle rows (org, cycle, amount, status, razorpay id)
- POST /admin/orgs/{id}/status {status: active|paused} — stop/resume service
- POST /admin/orgs/{id}/plan {plan: solo|clinic|multi} — upgrade/downgrade
- POST /admin/orgs/{id}/hard-block {enabled} — block calls once minutes exhausted

## Hard-block enforcement (voice agent entrypoint)
After branch→org resolve: org paused/cancelled OR (hard_block_on_exhaust AND
month minutes >= included) → answer the call, speak ONE polite Telugu line
("service temporarily unavailable, contact the clinic directly"), hang up.
Never dead air (RULE 8). Block check is one indexed call_logs SUM.

## Migration
organizations + hard_block_on_exhaust BOOLEAN NOT NULL DEFAULT false.
org_status enum already has paused — reused for "stop services".

## Frontend (Admin.jsx rebuild — GSAP + taste)
- Hero numerals w/ count-up: Clients (+MoM), Minutes month (+MoM), Revenue,
  Profit (green/red), Calls today, Total minutes all-time.
- 6-month bars: revenue vs expense + minutes line (scaleY stagger, reduced-motion gated).
- Approaching-limit callout (>=80% used), exhausted highlighted.
- Clinic ledger: plan chip, status chip, usage bar (amber>=80%, red exhausted),
  ₹ revenue/expense/profit, bookings, per-row actions: Pause/Resume,
  plan select, hard-block toggle.
- Payments section (BillingCycle rows; empty state until Razorpay ships).

# Autopay (UPI / e-mandate) — design

**Status:** approved in principle by Vinay 2026-08-07; NOT implemented yet.
**Why:** *"each month doctors keeping track of patients is kind of hard."*
Chasing a manual payment every month is work for the clinic and a collections
risk for us. Autopay makes it the platform's job.

## Vinay's three decisions (2026-08-07)

1. **Charge base + the PREVIOUS month's overage together, one debit per cycle.**
2. **Autopay REPLACES manual payment** — "similar to most platforms like
   Claude, ChatGPT". Not an option alongside it.
3. **New signups only.** Existing clinics stay on the manual flow; no migration.

## The billing shape this implies

Base is charged **in advance**, usage **in arrears** — one debit, two
components:

```
cycle N debit  =  base(plan, cycle N)  +  overage(cycle N-1)
```

The first cycle therefore has no overage component (there is no cycle 0), which
also means signup collects a clean, predictable first amount. That matches the
existing activation model: a new org starts `paused` and the first successful
payment activates it (free trial was removed 2026-07-17).

**Worked example, Clinic plan (₹9,999, 1,500 min included, ₹5/min overage):**

| Cycle | Minutes used | Debit |
|---|---|---|
| 1 (signup) | 1,720 | ₹9,999 (base only) |
| 2 | 1,400 | ₹9,999 + (220 × ₹5) = ₹11,099 |
| 3 | — | ₹9,999 + ₹0 = ₹9,999 |

GST follows `billing_math.GST_WAIVED` exactly as today — autopay must not
become a second place where tax is decided.

## Why a mandate, not a Razorpay Subscription

Razorpay Subscriptions bill a **fixed** amount per cycle. Our amount varies with
overage, so the right primitive is a **UPI Autopay / e-mandate** with a
`max_amount` ceiling the clinic approves once, then a variable debit each cycle.

Two constraints that shape everything:

- **Pre-debit notification is mandatory**, at least **24 hours** before each
  debit. Miss it and the debit is rejected. So the cycle needs a notify step,
  not just a charge step.
- **`max_amount` is a hard ceiling.** A clinic that blows far past its included
  minutes can produce a debit above the mandate. Pick the ceiling with real
  headroom (proposal: `max(3 × base, base + 5000)`) and treat "amount exceeds
  mandate" as a first-class failure that falls back to a payment link.

## Flow

```
SIGNUP
  create Razorpay customer -> create mandate (authorisation txn, ₹1 refunded
  or ₹0 where supported) -> store token/mandate id on Organization
  -> org stays `paused` until the FIRST debit succeeds

EACH CYCLE (job, daily)
  T-1 day : close the previous cycle, compute base + overage, write a
            BillingCycle row (status=open), send the pre-debit notification
  T       : debit the mandate for that exact amount -> status=paid
  failure : retry ladder, then suspend
```

## What already exists (do not rebuild)

- `Organization.razorpay_customer_id`, `.razorpay_subscription_id`
- `BillingCycle` with `base_amount`, `overage_minutes`, `overage_amount`,
  `status`, and a **unique** `razorpay_payment_id` (webhook replay safety)
- `billing_math.py` — the single source of truth for plan economics, GST and
  the overage rate. Autopay reads it; it never re-derives a price.
- Metering: minutes come from summing `call_logs.duration_seconds` over the
  cycle (not a stored counter).

## What to build

1. **Schema (migration):** `Organization.mandate_id`, `mandate_status`
   (`none|pending|active|paused|revoked|failed`), `mandate_max_amount`,
   `autopay_enabled`. `BillingCycle.debit_attempts`, `notified_at`,
   `razorpay_invoice_id`.
2. **`backend/services/autopay.py`** — create mandate, send pre-debit notice,
   debit, handle failure. All amounts come from `billing_math`.
3. **Webhooks** — `subscription.charged`, `payment.failed`,
   `subscription.halted`, mandate revoked. Idempotent on
   `razorpay_payment_id` (the unique constraint is the backstop).
4. **Job** — daily; closes cycles, sends notices at T-1, debits at T. Idempotent
   per (org, cycle): a re-run must never double-debit.
5. **Failure ladder** — retry at +1d, +3d, +5d; then `paused` (the AI line
   answers with the blocked line, same as today). Every step notifies the
   clinic.
6. **Frontend** — mandate setup in onboarding, autopay status + next debit date
   + amount on the billing page, and a way to fix a failed mandate.

## Hard requirements

- **Never double-debit.** Idempotency key per (org, cycle); the unique
  `razorpay_payment_id` is the last line of defence. This is the money-path
  equivalent of RULE 2 and deserves the same concurrency tests.
- **Never debit without the 24h notice** — legally required and Razorpay
  rejects it anyway. Assert the ordering in tests.
- **Never debit an amount the clinic cannot predict.** The notice states the
  exact figure and its two components.
- A failed debit **suspends**, never silently keeps serving.
- Test money paths first (CLAUDE.md): concurrency, idempotency, replay.

## Vinay's remaining four decisions (2026-08-07) — all settled

1. **Ceiling: "as low as possible and still covered... calculate it cleverly by
   taking max calls cases into consideration."** Implemented as
   `billing_math.mandate_max_amount()` (tested).
2. **Suspend after the 3rd failed retry.**
3. **Mid-cycle upgrade rolls into the next debit** ("that will be generally
   followed case right" — yes, it is the industry norm and it avoids a second
   debit the clinic did not expect).
4. **The ₹1,499 WhatsApp add-on is inside the autopay debit**, not billed
   separately.

### How the ceiling is derived

The theoretical maximum is useless: one DID carries one call at a time, so a
month holds ~43,200 minutes and a ceiling covering that would run to lakhs —
exactly what makes a clinic refuse to sign. Two bounds make it realistic:

- **Volume bound** — cover a clinic running **3× its plan** (its bucket plus
  two more). Beyond that it is an upgrade conversation, not a normal month.
- **Money bound** — overage capped at **3,000 minutes (₹15,000)**. Past that
  the mandate is the wrong instrument and the debit uses the payment-link
  fallback, which must exist regardless: no finite ceiling covers every case.

**GST headroom (×1.18) is applied even while `GST_WAIVED` is True.** If GST is
switched back on, every debit rises 18% overnight — a ceiling set without it
would reject every debit and force every clinic to re-authorise. Unused ceiling
costs nobody anything.

| plan | base | ceiling | with WhatsApp add-on |
|---|---|---|---|
| Lite | ₹1,999 | ₹4,500 | ₹6,000 |
| Starter | ₹5,999 | ₹15,500 | ₹17,500 |
| Clinic | ₹9,999 | ₹29,500 | — (included) |
| Multi | ₹17,999 | ₹39,000 | — (included) |
| WhatsApp-only | ₹1,499 | ₹2,000 | — |

1.3×–3.0× the monthly price. Tests assert both directions: the ceiling covers
its own worst case *with GST back on*, and never exceeds 3.5× the price.

## Still open

- Exact Razorpay product choice for the authorisation transaction (₹1 refunded
  vs ₹0 where the PSP supports it) — needs the live account to confirm.
- Whether a clinic that hits the payment-link fallback twice should be prompted
  to upgrade automatically.

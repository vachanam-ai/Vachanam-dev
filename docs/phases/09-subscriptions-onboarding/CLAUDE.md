# Phase 9 — Subscriptions + Onboarding ⬜ TODO

**Goal:** Convert from one-time Razorpay checkout (Phase 3) to recurring SaaS subscriptions. Build the new-clinic onboarding wizard. Provision a Vobiz DID for each new clinic. First paying customer becomes possible.

**Effort:** 3-4 days. **Prerequisites:** Phases 4, 5, 6, 7, 8 ✅. Razorpay live mode activated (KYC done). Vobiz partner account active.

---

## Two flows

### A. Subscription billing

Razorpay Standard Checkout (Phase 3) creates one-time orders. For SaaS recurring billing, use **Razorpay Subscriptions API** instead.

Steps in Razorpay dashboard (one-time, owner action):
1. Create 3 plans matching the canonical pricing — **resolve pricing decision in [STATUS.md](../../STATUS.md) first**
2. Copy plan IDs into `.env`: `RAZORPAY_PLAN_SOLO_ID`, `RAZORPAY_PLAN_CLINIC_ID`, `RAZORPAY_PLAN_MULTI_ID`
3. Configure webhook URL → `https://<backend>/webhook/razorpay`, copy `RAZORPAY_WEBHOOK_SECRET`
4. Subscribe to events: `subscription.charged`, `subscription.completed`, `subscription.cancelled`, `subscription.paused`, `payment.failed`

Backend additions:
- `backend/services/razorpay_subscription.py` — `create_subscription(plan_id, customer_email, trial_days=14)`, `cancel_subscription(sub_id)`, `pause_subscription(sub_id)`
- `backend/routers/billing.py`:
  - `POST /billing/subscribe` — body `{plan}` → creates Razorpay customer + subscription → returns `subscription_id` to frontend → frontend opens Razorpay checkout with `subscription_id` instead of `order_id`
  - `POST /webhook/razorpay` — verify `X-Razorpay-Signature` HMAC, dispatch by event type, update `BillingCycle` rows
- `backend/jobs/billing_cycle.py` — daily midnight: close yesterday's cycle for Solo plans (compute overage from `calls.duration_seconds`, charge via `subscription.charge_addon` API)
- `backend/jobs/trial_expiry.py` — daily 10 AM: orgs with `trial_ends_at < today AND status='trial'` → send WA payment link, on day 14 set `status='paused'`

### B. Onboarding wizard

`frontend/src/pages/Onboarding.jsx` — multi-step:
1. **Sign-in** with Google
2. **Clinic info** — name, city, address, owner phone
3. **Pick plan** — Solo / Clinic / Multi cards
4. **Pay** — Razorpay checkout for first month (trial: skip payment, schedule for day 14)
5. **Provision** — backend kicks off:
   - `provision_new_clinic()` in `backend/services/onboarding_service.py`:
     - Create `Organization`, `User` (owner), first `Branch`
     - Call `vobiz_partner.provision_did(branch_id, city)` → returns DID number + SIP credentials
     - Save DID + SIP details on `Branch` row
     - Create LiveKit dispatch rule mapping DID → agent room
     - Send WA welcome with call-forwarding instructions
6. **Add first doctor** — name, WA number, specialization, working hours, daily limit
7. **Done** — redirect to `/dashboard`

Vobiz Partner API (per [docs.vobiz.ai/integrations/livekit](https://docs.vobiz.ai/integrations/livekit)):
- `backend/services/vobiz_partner.py`:
  - `provision_did(branch_id, city) -> {did_number, sip_domain, sip_username, sip_password}`
  - Auth: `VOBIZ_PARTNER_AUTH_ID` + `VOBIZ_PARTNER_AUTH_TOKEN`
  - LiveKit SIP setup: `livekit_api.create_sip_outbound_trunk(...)` with the returned credentials
  - LiveKit dispatch: route `did_number → agent_room`

---

## Acceptance criteria

```
[ ] POST /billing/subscribe with plan=Clinic creates Razorpay subscription, returns subscription_id
[ ] Frontend Razorpay modal accepts the subscription_id and confirms first payment in test mode
[ ] Razorpay webhook receives subscription.charged → BillingCycle row inserted with status='paid'
[ ] Invalid X-Razorpay-Signature → 400 (no DB write)
[ ] Onboarding wizard completes end-to-end in test mode: org + user + branch + DID + first doctor in DB
[ ] Vobiz DID returned, saved to branch.did_number, branch.vobiz_did_id
[ ] LiveKit dispatch rule visible in LiveKit console for the new DID
[ ] Trial org on day 14: WA payment link arrives at 10 AM IST, status flips to paused if unpaid
[ ] Solo plan overage: simulate 110 min usage → BillingCycle.overage_amount > 0, addon charge invoiced via Razorpay
```

---

## What this phase does NOT do

- ❌ Doesn't change the marketing site (vachanam.in stays as-is)
- ❌ No usage-based billing for Clinic/Multi (those are flat; only Solo has per-minute overage)
- ❌ No proration on plan changes (post-MVP — for now, plan change happens at next cycle start)
- ❌ No refund flow (post-MVP — refund manually via Razorpay dashboard)

Move on to [Phase 10](../10-deployment/CLAUDE.md).

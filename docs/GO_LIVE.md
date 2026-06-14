# Vachanam — Go-Live Checklist

**Owner:** Vinay. **Last updated:** 2026-06-13.

Split into **what code does** (done / in repo) and **what Vinay must do** (accounts,
money, KYC, secrets, physical actions). Code items below are implemented + tested
unless marked otherwise. External items are blocking — the software cannot do them.

---

## A. Code — DONE this sprint (in repo, tested)

- [x] **Payments billing** (TD-019/025) — `create-order` is auth-gated + plan-priced
  (server-derived amount) + sets order `notes` server-side; `/api/razorpay-webhook`
  (HMAC-verified) is the authoritative activation → org `active` + paid `BillingCycle`,
  idempotent on `razorpay_payment_id`. Tests: `test_payments_billing.py`.
- [x] **Metering durability** (TD-027/F6) — `CallLog` written at call start, finalized
  at end; `finalize_stale_calls` job reconciles crash-stranded rows (every 30 min).
  Tests: `test_metering_durability.py`.
- [x] **Patient vs clinic cancel** (TD-020) — `cancelled_by_patient` enum + migration
  `j6cancelpatient2026`; analytics + rebook framing split.
- [x] **Doctor calendar-id change** (TD-023) — moves the recurring hours event to the
  new calendar instead of 404-ing.
- [x] **Recording hard-off in production** — `recording_allowed` is false in prod
  regardless of the flag (DPDP / no-voice-recording).
- [x] **Dockerfiles non-root** (TD-014); **CSP** `frame-ancestors` + `upgrade-insecure-requests`.
- [x] Round-4/5 bounty fixes (token calendar, DID fallout, OTP fail-closed, JWT 8h,
  call ceiling, single-default-doctor, staff password strength, etc.).

## B. Code — still open (decide / post-launch)

- [ ] **TD-021** urgent walk-in: bypass full queue, or remove the flag? **Vinay decision.**
- [ ] **TD-026** token capacity frees same-day cancelled seats (bounded; daily reset).
- [ ] **G15** CSP `img-src`/`style-src` tightening — needs a frontend render check first.
- [ ] **PWA offline queue** — not implemented; decide if MVP needs it.

---

## C. Vinay — external accounts (BLOCKING; only you can do these)

- [ ] **Razorpay**: complete KYC; get `rzp_live_*` keys; create the 3 subscription
  plans → `RAZORPAY_PLAN_SOLO_ID` / `_CLINIC_ID` / `_MULTI_ID`; set a webhook secret
  → `RAZORPAY_WEBHOOK_SECRET`; **register the webhook URL** `https://<api>/api/razorpay-webhook`
  in the Razorpay dashboard for `order.paid` + `payment.captured` events.
- [ ] **Vobiz**: provision a DID, finish KYC (`is_verified`), point the SIP trunk at
  the LiveKit inbound endpoint.
- [ ] **LiveKit (prod)**: create project; inbound + outbound trunks; a dispatch rule
  that passes the `trunkPhoneNumber` attribute (RULE 5 depends on it) → `LIVEKIT_URL`,
  `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `INBOUND_TRUNK_ID`, `OUTBOUND_TRUNK_ID`.
- [ ] **Sarvam / Gemini / OpenAI**: prod API keys with quota.
- [ ] **Google**: `google-service-account.json` on the API host; each clinic shares its
  calendar with the service account (the Settings page guides this + "Test connection").
- [ ] **Neon / Upstash**: prod Postgres + Redis → `DATABASE_URL`, `REDIS_URL`.
- [ ] **MSG91 (SMS)** — `MSG91_AUTH_KEY` + approved `MSG91_SENDER_ID`. **HARD-REQUIRED
  in production**: signup verification is **mobile-only** (decision 2026-06-14). With no
  SMS provider in prod the code is neither sent nor echoed → **nobody can sign up**.
  Email OTP is retired; SMTP is optional (transactional email only, not signup).

## D. Vinay — deploy + infra

- [ ] Set all ~26 env vars (`.env.example`) on **Render** (API), **Fly** (agent),
  **Cloudflare Pages** (frontend). Never commit `.env` or the SA JSON.
- [ ] `alembic upgrade head` on the prod DB (head = `j6cancelpatient2026`).
- [ ] Fly Mumbai: open **UDP 5060** (SIP) + **10000-60000** (RTP).
- [ ] DNS/TLS: vachanam.in → frontend, `api.` → Render; MX for hello@vachanam.in.
- [ ] `APP_ENV=production` (disables /docs, /dev/test, OTP echo, recording).
- [ ] Strong rotated `JWT_SECRET`; `FRONTEND_URL` = prod origin (CORS).
- [ ] UptimeRobot → `GET /health`.

## E. Vinay — validation before first paying clinic

- [ ] **One real inbound call**: dial the DID → AI answers in Telugu → books → calendar
  event appears (slot doctor) → booking shows in the receptionist queue.
- [ ] One real subscription: pay via Razorpay → webhook flips org to `active` + a
  `BillingCycle` row appears.
- [ ] Confirm `recording_allowed` is false in prod (it is, by code — just verify env).

---

## Critical path (shortest route to live)

Razorpay live + plans + webhook (C) → LiveKit/Vobiz/DID wired (C) → secrets set +
migrate + deploy (D) → one real call + one real payment (E). Everything else is
polish or post-launch.

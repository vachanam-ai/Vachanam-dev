# Phase 3 — Razorpay Standard Checkout ✅ DONE (test mode, standalone)

> **Note:** `backend/payments_test_app.py` referenced below was retired in Phase 4 (deleted, commit `6ffa2d7`). The payments router now mounts in [`backend/main.py`](../../../backend/main.py) at `/api`.

**Goal:** A one-time payment can be initiated from the Vachanam landing page, processed through Razorpay's hosted modal, signed-back, and verified server-side.

This is **NOT** the SaaS subscription billing (that's Phase 9). This is one-time checkout — the primitive you compose with for any paid action.

---

## What was built

### Backend
- [`backend/routers/payments.py`](../../../backend/routers/payments.py):
  - `POST /api/create-order` — creates a Razorpay order via Python SDK. Returns `{order_id, amount, currency, key_id}`. `key_id` is returned from server so the frontend never needs `VITE_RAZORPAY_KEY_ID`.
  - `POST /api/verify-payment` — HMAC-SHA256(`order_id|payment_id`, KEY_SECRET) via `hmac.compare_digest`. Returns 400 on mismatch (never marks paid).
  - Amount validation: Pydantic `Field(..., ge=100)` rejects amounts < 100 paise (₹1) before reaching Razorpay.
- [`backend/payments_test_app.py`](../../../backend/payments_test_app.py) — standalone FastAPI mounting only the payments router. **Temporary** — Phase 4 deletes this when `backend/main.py` exists.

### Frontend
- [`backend/static/index.html`](../../../backend/static/index.html) — 1:1 mirror of [vachanam.in](https://vachanam.in/) (947 lines, fonts: Outfit/Spectral/Pacifico, color palette `#006B6B` teal). Three "Get started" buttons in the Pricing section trigger the Razorpay flow.
  - Yellow TEST MODE banner at the top with instructions
  - Bottom toast for payment success/failure/cancel
  - Loads `checkout.razorpay.com/v1/checkout.js`
- [`backend/static/razorpay-test.html`](../../../backend/static/razorpay-test.html) — dev-only single-button page at `/dev/test`, type-any-amount

### Verified end-to-end
- Real Razorpay test orders created (e.g. `order_SsFxpRSIGK6my1`, `order_SsG7gVoUua7dWT`) and confirmed via `client.order.all()` querying the real Razorpay API
- Signature verification round-tripped with known-good and known-bad signatures (200 / 400)
- Two real payment attempts logged at Razorpay against `order_SsG2hVpHBvvxeT` — both failed because of domestic-only card setting + test card BIN treated as international (expected test-mode behavior, not a code bug)

---

## Files this phase touches

```
backend/routers/payments.py
backend/static/index.html
backend/static/razorpay-test.html
backend/payments_test_app.py            ← Phase 4 deletes
.env (RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET filled with rzp_test_*)
```

---

## What this phase is NOT

- ❌ Not a subscription. Razorpay subscriptions (`RAZORPAY_PLAN_*_ID`) live in Phase 9.
- ❌ Not the production landing page. `vachanam.in` continues to be the marketing site (hosted wherever it is now). This local mirror exists only as a Razorpay test target. The production marketing-to-paid-signup flow is wired in Phase 9.
- ❌ Not wired into the real backend yet. Lives inside `payments_test_app.py`. Phase 4 mounts it on `backend/main.py`.
- ❌ Not the receptionist app or owner dashboard. Those are different React apps (Phase 7, 8).

---

## Known issues / to address before live mode

| Issue | Fix-in |
|---|---|
| `rzp_test_*` keys filled. Live mode requires `rzp_live_*` after Razorpay account activation + KYC. | Phase 9 |
| Test mode: card `4111 1111 1111 1111` is rejected as "international" because account is domestic-only. Fix in Razorpay dashboard → Configuration → International Payments. | Owner action, before live |
| Test mode: UPI tab shows QR only (no "Enter UPI ID" field). Fix in dashboard → Configuration → Payment Methods → UPI → enable Collect flow. | Owner action, before live |
| Starter price on the mirror was lowered to ₹99 for self-test. Restore to canonical price (Starter ₹6,999 OR Solo ₹1,999 — see [STATUS.md](../../STATUS.md) pricing decision) before linking from real marketing. | Phase 9 |

---

## How to bring this phase up

```bash
docker-compose up -d
uvicorn backend.payments_test_app:app --port 8000 --reload
# open http://localhost:8000/
# click any Get started → in modal: Netbanking → any bank → Pay → Success
```

After Phase 4, the equivalent is `uvicorn backend.main:app --port 8000 --reload` and the route lives at the same path.

---

## What this phase does NOT do

- Does not persist a `Payment` record (no DB write on success — the verify endpoint is stateless). When Phase 9 wires subscriptions, payment events become webhook-driven and persist to `BillingCycle`.
- Does not handle webhooks (`POST /webhook/razorpay`). That's Phase 9, needs `RAZORPAY_WEBHOOK_SECRET`.

Move on to [Phase 4](../04-backend-core/CLAUDE.md).

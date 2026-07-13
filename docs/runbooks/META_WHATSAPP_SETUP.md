# Meta WhatsApp setup — Vinay's checklist (one-time, ~1–2h)

Spec: `docs/superpowers/specs/2026-07-13-whatsapp-mvp2-design.md`.
Do Phase A steps 1–6 anytime. Step 7 (webhook) waits until Claude confirms
the endpoint is deployed. Phase B happens per clinic, after the build.

## Phase A — one-time platform setup

**A1. Meta Business Portfolio**
- https://business.facebook.com → Create account/portfolio.
- Business name: `Vachanam`, email `hello@vachanam.in`, real address.
- Use your normal Facebook login (the portfolio is separate from your profile).

**A2. Developer app**
- https://developers.facebook.com → My Apps → Create App.
- Use case: **Other** → type: **Business**. Name: `Vachanam`.
- Connect it to the `Vachanam` business portfolio when asked.

**A3. Add WhatsApp product**
- In the app dashboard → Add product → **WhatsApp** → Set up.
- This auto-creates a WhatsApp Business Account (WABA) + a FREE **test
  number** (+1 …). The test number can message up to 5 whitelisted numbers —
  we build and demo everything on it before any clinic is linked.
- On the API Setup page, note:
  - **WABA ID**  → env `META_WABA_ID`
  - **Phone number ID** (of the test number) → env `META_PHONE_NUMBER_ID`
- Add your own WhatsApp number to the test number's allowed recipients
  (API Setup → To → Manage phone number list) and send the sample message —
  confirms the pipe works.

**A4. Permanent token (system user)**
- business.facebook.com → Settings (gear) → Users → **System users** → Add.
- Name `vachanam-backend`, role **Admin**.
- Assign assets: the app (full control) + the WABA (full control).
- Generate token: select the app, expiry **Never**, permissions:
  `whatsapp_business_messaging` + `whatsapp_business_management`.
- Copy ONCE → env `META_ACCESS_TOKEN`. (Shown only once — if lost, generate a
  new one.)

**A5. App secret**
- App dashboard → App settings → Basic → **App secret** → Show.
- → env `META_APP_SECRET`.

**A6. Payment method**
- business.facebook.com → Settings → Billing → add card/UPI on the WABA.
- Free-tier/test messages don't bill, but template sends to real numbers do
  (₹0.115–0.145 each) — needs a payment method attached before Phase B.

**A7. Webhook — WAIT for Claude's "endpoint live" confirmation**
- App dashboard → WhatsApp → Configuration → Webhook → Edit:
  - Callback URL: `https://vachanam-backend.onrender.com/webhooks/whatsapp`
  - Verify token: the value of `META_WEBHOOK_VERIFY_TOKEN` (generate any long
    random string; same value goes in Render env).
- Click Verify and save (Meta calls the endpoint — it must be deployed).
- Webhook fields → subscribe to **messages**.

**A8. Render env vars** (Dashboard → vachanam-backend → Environment):
```
META_ACCESS_TOKEN=        (A4)
META_PHONE_NUMBER_ID=     (A3 — test number for now)
META_WABA_ID=             (A3)
META_WEBHOOK_VERIFY_TOKEN=(A7 — your random string)
META_APP_SECRET=          (A5)
```
Missing vars = WhatsApp features stay no-op (safe).

**A9. Business verification — start when GST certificate arrives (TD-038)**
- business.facebook.com → Settings → Security Centre → **Start verification**.
- Upload GST certificate / incorporation proof; 2–10 business days.
- Until verified: max 2 linked phone numbers, 250 business-initiated
  conversations/day. Verified: 20 numbers, higher tiers. Blocks REAL clinic
  numbers at scale, does NOT block the test-number pilot.

## Phase B — per clinic (~15 min, concierge, after build + A9 for real numbers)

**B1.** Clinic must have WhatsApp Business **app** (not personal WhatsApp) on
their number, app version ≥ 2.24.17, phone in hand.

**B2.** business.facebook.com → WhatsApp accounts → the WABA → Phone numbers →
**Add phone number**: clinic's number, display name = clinic's public name
(Meta reviews the name — must match their signage/website), category Medical
& health.

**B3.** Verify via OTP delivered to the clinic's phone. When the number is
detected as active on the WhatsApp Business app, choose the **Coexistence /
"keep using the app"** path (QR scan from the clinic's app: Settings →
Linked devices → link to API). Their chats and app keep working; API rides
the same number.
- ⚠ If Meta offers ONLY migration (loses app access) for this number: STOP,
  tell Claude — fallback path is Embedded Signup (post-verification) and we
  schedule accordingly. Do not migrate a clinic off their app.

**B4.** Copy the new number's **Phone number ID** → set it on the branch via
the admin endpoint (Claude provides the exact call in the pilot runbook).

**B5.** Test on the clinic's phone: one booking-confirmation template + a
free-text "hi" reply. Both sides working = clinic live.

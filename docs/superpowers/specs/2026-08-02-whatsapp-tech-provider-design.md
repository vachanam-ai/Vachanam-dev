# WhatsApp Tech Provider — end-to-end integration design

**Date:** 2026-08-02 · **Decided by:** Vinay · **Supersedes** the Coexistence
assumption in `2026-07-13-whatsapp-mvp2-design.md` (single Vachanam-owned WABA,
one platform token). The message/webhook/template layer built by that plan is
KEPT — only the ownership and credential model change.

**Goal:** many clinics, each with its own WhatsApp number, onboarded self-serve
under Vachanam's Meta app; the AI answers every patient of every clinic
separately; Vachanam charges a monthly fee, Meta bills each clinic directly.

**Model chosen: (A) the clinic owns its WABA.** Vachanam is an independent
**Tech Provider**. Each clinic gets (or brings) its own WhatsApp Business
Account, grants our app access through **Embedded Signup**, and adds its own
payment method. We never own their number and never pay their message bill.

Why not (B) one Vachanam-owned WABA hosting clinic numbers: ~25 numbers per
WABA ceiling, every clinic's quality rating pooled into one account (one
clinic's spam throttles all of them), and we would carry every clinic's Meta
bill and its GST. (A) matches the Tech Provider path already in review.

---

## 1. What already exists (do not rebuild)

| Piece | Location | State |
|---|---|---|
| `GET/POST /webhooks/whatsapp` — verify handshake, HMAC, idempotent, always-200 | `backend/routers/whatsapp_webhook.py` | live in prod |
| Branch resolved by RECEIVING number (`Branch.wa_phone_number_id`) | `schema.py` | done — RULE 5 |
| Send text / template / interactive, retried, never raises into a booking | `backend/services/wa_service.py` | done — RULE 4 |
| Template payload builders (`booking_confirm`, `appt_reminder`, `rating_ask`, `leave_rebook`) | `backend/services/wa_templates.py` | done |
| Inbound free-text (Gemini) + buttons + ratings | `wa_chat.py`, `wa_actions.py` | done |
| Per-patient conversation state | `WhatsAppSession` table | done |
| Plan gate `WHATSAPP_PLANS = {clinic, multi}` | `billing_math.py` | done |
| Evening rating-ask job | `backend/jobs/wa_rating_ask.py` | done |

**One webhook endpoint serves every clinic.** Meta delivers all subscribed
WABAs' events to the app's single callback URL; the payload's
`value.metadata.phone_number_id` picks the branch. Nothing per-clinic to host.

## 2. What changes

Today every send uses ONE platform token (`settings.meta_access_token`). With
client-owned WABAs each clinic has its own token, so:

1. `Branch` gains `wa_waba_id`, `wa_token_enc` (Fernet, never plaintext),
   `wa_verified_name`, `wa_status`, `wa_connected_at`, `wa_templates_synced_at`.
2. `wa_service` reads the **branch's** token, falling back to the platform token
   only when a branch has none (keeps the existing test WABA path working).
3. New onboarding endpoint: Embedded Signup code → token → subscribe → register
   → persist → seed templates.
4. Templates live per WABA, so each clinic needs its own approved copies.
5. Offboarding: unsubscribe + forget the token when a clinic churns.

---

## 3. End-to-end flows

### 3.1 Clinic onboarding (self-serve, ~3 min)

```
Clinic owner (Vachanam Settings)
  └─ "Connect WhatsApp" → Embedded Signup popup (Meta-hosted)
        ├─ picks/creates their Meta business + WABA
        ├─ adds their phone number, verifies by OTP
        └─ grants our app whatsapp_business_messaging + _management
  → popup returns { code, waba_id, phone_number_id }
POST /branches/{id}/whatsapp/connect  (org_admin only)
  1. exchange code    GET  /oauth/access_token?client_id&client_secret&code
  2. subscribe app    POST /{waba_id}/subscribed_apps      ← no webhooks without this
  3. register number  POST /{phone_number_id}/register {pin}
  4. persist          wa_waba_id, wa_phone_number_id, wa_token_enc, wa_status='connected'
  5. seed templates   POST /{waba_id}/message_templates × 4 (async, best-effort)
```

Every step is idempotent — a retried connect on an already-connected branch
re-subscribes and re-persists rather than erroring.

### 3.2 Inbound patient message (already built, unchanged)

```
patient → clinic's number → Meta → POST /webhooks/whatsapp (one endpoint, all clinics)
  HMAC check → idempotency SETNX wa:msg:{id} → phone_number_id → Branch (RULE 5)
  → WhatsAppSession for THAT patient → wa_chat/wa_actions → reply with the branch's token
```

Patients never collide: state is keyed `(branch_id, patient phone)`, and the
branch comes from the number that was dialled, never from the sender.

### 3.3 Outbound (booking confirm, reminder, rating, rebook)

Unchanged callers; `wa_service` just picks the branch's token now. Sends stay
best-effort — RULE 4, a WhatsApp failure never fails a booking.

### 3.4 The 24-hour window (shapes everything)

A patient message opens a 24h service window: free-form replies allowed, and
service conversations are free under Meta's current per-message pricing.
Outside the window only an approved **template** may re-open the thread — which
is exactly what the reminder/rating/rebook jobs already send. The AI must never
try to answer outside the window with free text; it will silently fail.

### 3.5 Offboarding

Clinic churns or disconnects → `DELETE /{waba_id}/subscribed_apps`, null the
token and ids, `wa_status='disconnected'`. Their WABA and number stay theirs.

---

## 4. Data model delta (one additive migration)

```
branches
  + wa_waba_id             VARCHAR(32)  NULL UNIQUE   -- their WABA
  + wa_token_enc           TEXT         NULL          -- Fernet(business token)
  + wa_verified_name       VARCHAR(120) NULL          -- display name Meta approved
  + wa_status              VARCHAR(16)  NOT NULL DEFAULT 'none'
                                        -- none | connected | disconnected | error
  + wa_connected_at        TIMESTAMPTZ  NULL
  + wa_templates_synced_at TIMESTAMPTZ  NULL
```

`wa_phone_number_id` already exists and stays the RULE-5 join key. Additive
only; existing rows read as `none` and behave exactly as today.

## 5. Credentials and isolation (RULE 1 + RULE 9)

- The clinic's token is a **business integration system-user token** — long-lived,
  no refresh loop. Stored Fernet-encrypted via `backend/services/crypto.py`
  (same pattern as the Vobiz SIP password), never logged, never returned by any
  API. The settings endpoint returns `wa_status` + last-4 of the number only.
- A send must resolve its token from the branch row it is sending for. A test
  proves branch A's token can never be used on branch B's number.
- App-level secrets (`META_APP_ID`, `META_APP_SECRET`, `META_CONFIG_ID`,
  `META_WEBHOOK_VERIFY_TOKEN`) stay in Render env; `.env.example` updated in the
  same commit (drift has bitten before).
- Logs: phone last-4 and ids only. Template bodies carry logistics only — no
  visit notes, no complaint text, no health data (RULE 9).

## 6. Meta console work (owner: Vinay, mostly waiting)

Phase 0 — approvals, in flight:
- [ ] Business verification (in review — everything is gated on it)
- [ ] App Review: advanced access to `whatsapp_business_messaging` **and**
      `whatsapp_business_management`; two videos (message send + template
      creation; screen recordings of API Setup cURL / WhatsApp Manager accepted)
- [ ] **Publish the app (App Mode → Live)** — unpublished apps receive test
      webhooks only, so no clinic message ever arrives

Phase 1 — wiring (doable today, unblocked):
- [ ] Callback URL `https://vachanam-backend.onrender.com/webhooks/whatsapp`
      (→ `https://api.vachanam.in/...` once DNS lands), verify token = Render's
      `META_WEBHOOK_VERIFY_TOKEN`
- [ ] Subscribe fields: `messages`, `message_template_status_update`,
      `account_update`
- [ ] Set `META_APP_SECRET`, `META_APP_ID` in Render
- [ ] Create the Embedded Signup **configuration** → `META_CONFIG_ID`

The test WABA / `+1 555…` number cannot serve production (5 recipients, no real
traffic). It stays useful as the platform-token fallback for our own testing.

## 7. Build phases

> **Amended 2026-08-02** by `2026-08-02-whatsapp-hub-cross-channel-design.md`
> §6/§9: P1 (Embedded Signup connect) is **no longer first**. We run "bridge
> mode" — the pilot number on Vachanam's own WABA, platform token — while
> business verification and App Review are pending, behind a per-branch token
> resolver so the switch to clinic-owned WABAs is a per-clinic flag flip, not a
> rewrite. Connect moves to slice 6 of that plan; everything below still applies
> when it is built.

**P1 — connect a clinic (the unblocking slice)**
- [ ] Migration + model fields (§4)
- [ ] `backend/services/wa_onboarding.py`: `exchange_code`, `subscribe_app`,
      `register_number`, `connect_branch` — each idempotent, each raising a
      typed error the endpoint maps to a clean 4xx
- [ ] `POST /branches/{id}/whatsapp/connect` (org_admin, audited,
      `branch.whatsapp_connected`), `DELETE …/whatsapp` for offboarding
- [ ] `GET /branches/{id}/settings` exposes `wa_status` + masked number
- [ ] `wa_service`: per-branch token, platform token as fallback
- [ ] Tests: happy path, replayed connect, subscribe failure leaves
      `wa_status='error'` and no half-written row, cross-branch token isolation,
      token never plaintext in DB or logs

**P2 — templates per WABA**
- [ ] `wa_templates.sync(branch)` — create the 4 templates on their WABA, record
      `wa_templates_synced_at`, tolerate "already exists"
- [ ] Consume `message_template_status_update` webhooks → store approval state
- [ ] Send path skips a template that is not approved yet (log, no crash)

**P3 — clinic-facing UI**
- [ ] Settings → "WhatsApp" card: Connect button (FB JS SDK, `config_id`),
      status chip (not connected / connected / needs attention), number +
      display name, Disconnect
- [ ] Empty-state copy explaining the clinic pays Meta for messages

**P4 — operations**
- [ ] Health: count of connected branches, last inbound per branch
- [ ] Watchdog alert when a connected branch stops receiving webhooks for 24h
- [ ] Runbook: number quality rating drop, template rejection, token revoked

## 8. Money

- Clinic adds its own payment method to its WABA (INR + 18% GST, billed by Meta).
- Meta's current model: customer-initiated **service** conversations are free;
  **template** messages (utility/marketing/auth) are billed per message. Our
  reminders and confirmations are utility templates → the clinic's cost. Verify
  live rates on Meta's pricing page before quoting.
- Vachanam's monthly fee is unchanged; WhatsApp remains a Clinic/Multi feature
  (`WHATSAPP_PLANS`). Lite/Starter clinics see the card disabled with an upsell.

## 9. Risks

| Risk | Mitigation |
|---|---|
| App not published → zero production webhooks | Explicit Phase-1 checklist item; health check counts inbound events after go-live |
| Clinic never adds a payment method → sends fail | `wa_status='error'` on the first billing rejection + dashboard banner |
| Template rejected by Meta | Send path skips unapproved templates; voice + dashboard paths unaffected |
| Token revoked by the clinic | Graph 401 → `wa_status='error'`, banner asks them to reconnect; never retried into a loop |
| One clinic's spam hurts others | Impossible under (A) — separate WABAs, separate quality ratings |
| Reply attempted outside the 24h window | Free-text replies gated on an open window; otherwise a template or nothing |

## 10. Definition of done

A second clinic can, without Vinay touching the Meta console: click Connect,
finish Embedded Signup, get its 4 templates approved, receive a patient message
that the AI answers in the clinic's language, and get a booking-confirmation
template — with its own number, its own bill, and no access to any other
clinic's data.

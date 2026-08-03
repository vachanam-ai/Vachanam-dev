# WhatsApp MVP1 — go-live runbook

Spec: `docs/superpowers/specs/2026-08-02-whatsapp-hub-cross-channel-design.md`,
`docs/superpowers/specs/2026-08-02-whatsapp-pricing-design.md`. Plan:
`docs/superpowers/plans/2026-08-02-whatsapp-mvp1-plan.md`.

This supersedes `docs/runbooks/META_WHATSAPP_SETUP.md` for the parts that
changed under the clinic-owned-WABA redesign (2026-08-02): each clinic now
gets its OWN WhatsApp Business Account, not a shared Vachanam number per
branch. `META_WHATSAPP_SETUP.md`'s Phase A (portfolio/app/system-user) is
still correct and not repeated here; `META_TEMPLATES.md` is **stale** — it
says to create every template twice (te + en). Templates are English-only
now (`wa_templates.template_lang()` always returns `"en"`) — create each
template ONCE, in English. `scripts/wa_create_templates.py` already reflects
this; the `.md` file does not.

---

## 1. Meta console order

Do these **in order** — later steps depend on earlier ones being live.

1. **App → Live.** App dashboard → top toggle "In development" → "Live".
   A dev-mode app can only message numbers on its allowed-recipient test
   list; nothing reaches a real patient until this flips.
2. **Payment method on the WABA.** business.facebook.com → Settings →
   Billing → add a card/UPI to the WABA. Utility templates outside the
   free tier bill the WABA owner directly — for the pilot number that is
   Vachanam; for a clinic's own WABA (Embedded Signup, Task 9) it is the
   clinic. No payment method = sends fail silently once the free tier is
   used up.
3. **Webhook + verify token.** App dashboard → WhatsApp → Configuration →
   Webhook:
   - Callback URL: `https://vachanam-backend.onrender.com/webhooks/whatsapp`
   - Verify token: any long random string — put the SAME value in
     `META_WEBHOOK_VERIFY_TOKEN` on Render *before* clicking Verify (Meta
     calls the endpoint synchronously; a mismatched or missing token 403s).
   - Subscribe to the **messages** field. Nothing else is consumed.
4. **Templates.** Run `scripts/wa_create_templates.py <WABA_ID>` (below) —
   do this AFTER the app is Live, or Meta review can stall in a dev-mode
   limbo. Wait for all four to show `APPROVED` (Business Manager → WABA →
   Message templates) before sending anything real.
5. **Pilot number.** Only after 1–4 are done: link a real (or the free
   test) number's `phone_number_id` to a branch with
   `scripts/wa_link_branch.py` and run the smoke test (§4) before telling
   any clinic it's live.

## 2. The five `META_*` Render env vars

Dashboard → `vachanam-backend` service → Environment:

| Var | What it is | Where to find it |
|---|---|---|
| `META_ACCESS_TOKEN` | System-user permanent token, `whatsapp_business_messaging` + `whatsapp_business_management` scopes | business.facebook.com → Settings → System users → generate (shown once) |
| `META_PHONE_NUMBER_ID` | The **platform/pilot** sending number's numeric ID | App dashboard → WhatsApp → API Setup, or `GET /<WABA_ID>/phone_numbers` |
| `META_WABA_ID` | The WhatsApp Business Account ID | App dashboard → WhatsApp → API Setup |
| `META_WEBHOOK_VERIFY_TOKEN` | Your own random string, must match step 1.3 above | you generate it |
| `META_APP_SECRET` | HMAC key the webhook uses to verify `X-Hub-Signature-256` | App dashboard → App settings → Basic → App secret |

Missing/blank vars are safe — every WhatsApp code path is a no-op when
unconfigured (`wa_service.wa_enabled` returns `False`), not a crash. These
five cover the **platform** (Vachanam-owned pilot WABA). A clinic that
connects its own WABA (Task 9, Embedded Signup) does NOT need its own Render
env vars — its Fernet-encrypted token lives in `Branch.wa_token_enc` and
`wa_service.token_for()` resolves per-branch automatically, falling back to
these platform vars ("bridge mode") only when a branch has no token of its
own.

## 3. `scripts/wa_create_templates.py <WABA_ID>`

Creates Vachanam's four templates (`booking_confirm`, `appt_reminder`,
`rating_ask`, `leave_rebook`) on a WABA, generated FROM the same shape
`backend/services/wa_templates.py` sends — so the script and the code cannot
silently drift apart the way the hand-edited `.md` copy already has.

```bash
python scripts/wa_create_templates.py <WABA_ID> --dry-run   # print, send nothing
python scripts/wa_create_templates.py <WABA_ID>             # create for real
```

Reads `META_ACCESS_TOKEN` from `.env` (never pass a token on the command
line). Idempotent — an already-existing template is reported and skipped, so
re-running after a partial failure is safe.

**Run this once per WABA.** Templates live PER WABA — approving them on the
pilot WABA does nothing for a clinic's own WABA once Task 9 ships. Every new
clinic WABA needs its own run of this script (or the equivalent step folded
into the Embedded Signup flow when that's built).

## 4. `scripts/wa_link_branch.py` — link a number to a branch (concierge)

Linking is manual/concierge for MVP1 — there is no self-serve "Connect"
button yet (that is Task 9, gated on Meta granting advanced access to
`whatsapp_business_messaging`/`whatsapp_business_management`). A super_admin
runs this after the clinic's number is added to the WABA and its
`phone_number_id` is known:

```bash
python scripts/wa_link_branch.py --phone-number-id <ID>
python scripts/wa_link_branch.py --phone-number-id <ID> --branch-id <uuid>   # skip owner login
```

It prompts for two session JWTs (clinic owner's, then your super_admin's —
`/auth/login` is Turnstile-protected, so the script can't sign in itself; copy
the token from DevTools → Application → Local Storage → `vachanam_jwt`), then
calls the audited `PATCH /admin/branches/{id}/whatsapp` endpoint. A
`phone_number_id` already claimed by another branch 409s — one WhatsApp
number belongs to exactly one clinic (RULE 1). This also flips
`Branch.wa_status` to `connected` (or back to `none` when cleared), which is
what `GET /branches/{id}/settings` surfaces as the read-only status chip in
Settings (WA MVP1 Task 8) — never the token itself.

## 5. Smoke test — `scripts/wa_smoke.py`

Sends one real `booking_confirm` template through the exact builder
production uses, straight to a phone:

```bash
python scripts/wa_smoke.py <PHONE_NUMBER_ID> <TO_NUMBER>              # send
python scripts/wa_smoke.py <PHONE_NUMBER_ID> <TO_NUMBER> --dry-run    # print payload only
```

`<TO_NUMBER>` is E.164 digits, no leading `+`. Before the app is Live it must
be on the WABA's allowed-recipient list (App dashboard → WhatsApp → API
Setup → To → Manage phone number list) or the send fails. Green run = the
token, the sending number, and the approved template all actually work
end to end — do this before telling any clinic they're live, and again for
every new clinic's own WABA once Task 9 ships.

## 6. Failure modes we actually hit (read this before you re-derive them)

- **A number already registered to a personal/business WhatsApp account
  cannot simply be "verified" onto the Cloud API.** Meta's number-migration
  path DELETES the existing WhatsApp account and every chat on it — there is
  no undo. **Never do this to a clinic's live number.** The safe path is
  **Coexistence** (link via QR from the clinic's own WhatsApp Business app,
  Settings → Linked devices) or **Embedded Signup** (Task 9) — both keep the
  clinic's existing chats and app access intact.
- **Registering a number CHANGES its `phone_number_id`.** The ID you noted
  during setup is not necessarily the ID you'll be sending from after
  registration/verification completes — always re-read
  `GET /<WABA_ID>/phone_numbers` right before linking, don't reuse a value
  you copied earlier in the process.
- **Templates live per-WABA and do not carry across accounts.** Approving
  `booking_confirm` on the pilot WABA does nothing for a clinic's own WABA.
  Run `wa_create_templates.py` again for every new WABA (§3).
- **`wa_skipped_plan` in the logs** means the org's plan does not include
  WhatsApp (`whatsapp_enabled()` in `billing_math.py` gates on
  `WHATSAPP_PLANS = {clinic, multi, wa}` or the add-on for lite/solo) — not a
  broken integration. Check the org's plan before debugging the webhook.
- **`wa_unknown_receiver` in the logs** means the branch is not linked yet
  (§4) — inbound is routed strictly by the RECEIVING `phone_number_id`
  (RULE 5), so an unlinked number's messages are logged and silently
  dropped, which looks identical to "the bot is dead" from the clinic's side.
- **A corrupt/undecryptable `wa_token_enc` fails CLOSED**, not open — it
  never falls back to the platform token, because that fallback would send
  the clinic's message from Vachanam's own WhatsApp identity (RULE 1,
  cross-tenant send). Symptom: `wa_token_undecryptable` in the logs and every
  send for that branch silently no-ops until the token is re-linked.

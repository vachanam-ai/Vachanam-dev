# WhatsApp Integration (MVP2) — Design

Date: 2026-07-13 · Approved by: Vinay (brainstorm session) · Status: spec for planning

## Decisions (locked in brainstorm)

| Decision | Choice | Why |
|---|---|---|
| Sender number | **Clinic's own WhatsApp number from day 1** via Meta Coexistence (no shared-Vachanam-number phase) | Vinay: "perfect from day 1, no changing back and forth". Coexistence is live in India — clinic keeps its WhatsApp Business app; API rides the same number. |
| Build path | **Direct Meta Cloud API** (no BSP, no unofficial bridges) | Raw Meta rates (utility ≈ ₹0.115/msg), no per-clinic BSP platform fee (₹1,000–2,500/mo would destroy the ₹6k/clinic margin), no third party in the PII chain. Unofficial WhatsApp-Web automation rejected: ToS violation + ban risk on clinic's real number. |
| Chat depth day 1 | **Buttons + Gemini for free text** | Quick-reply buttons carry ~90% of interactions deterministically; Gemini handles typed free text with a small tool set. New bookings + anything medical → tap-to-call the clinic (voice agent). |
| Outbound moments | **All four**: booking confirmation, appointment reminder, rating ask after visit, doctor-leave rebook ping | Vinay selected all. Reminder/rebook ride ALONGSIDE the existing voice calls (not replacing them yet). |
| Plan gating | **Clinic + Multi only** | Vinay's positioning call. Starter stays voice-only. |

## Constraints honoured (CLAUDE.md hard rules)

- **RULE 1** — every send and every inbound action is branch-scoped; per-clinic
  `phone_number_id` credentials live on the Branch row.
- **RULE 2/3** — WhatsApp reschedule/cancel reuse the SAME atomic
  assign/confirm/release paths the voice agent uses. No new booking-write code.
- **RULE 4** — WhatsApp is a NOTIFICATION channel: a failed send never fails or
  blocks a booking (send is fire-and-forget with tenacity retry + loud log).
  For inbound-initiated writes (reschedule via chat) the booking write is the
  action itself and fails cleanly like the voice path.
- **RULE 5** — inbound branch context comes from the RECEIVING clinic number
  (`metadata.phone_number_id` on the webhook event → Branch lookup), never from
  the patient's number.
- **RULE 7** — Gemini chat prompt carries the same no-medical-judgment
  discipline as the voice prompt; medical anything → clinic tap-to-call link.
- **RULE 8** — Meta API failures degrade silently for outbound; inbound errors
  reply with a static "please call us" line, never dead silence.
- **RULE 9** — message bodies carry booking logistics only (doctor, date/time,
  token, address). No complaints, no visit notes, no health details. Logs:
  last-4 + IDs.

## Architecture

```
Patient's WhatsApp  ⇄  Meta Cloud API  ⇄  Vachanam backend (Render)
                                             │
        POST /webhooks/whatsapp  ────────────┤  whatsapp_webhook.py (NEW router)
        (verify handshake + X-Hub-Signature-256 HMAC, app secret)
                                             │
                    wa_service.py (NEW) ─────┤  template sends + session replies
                    wa_chat.py (NEW)  ───────┤  Gemini intent chat (free text)
                    MetaService (existing stub) → thin wrapper over wa_service
```

### New components

1. **`backend/routers/whatsapp_webhook.py`**
   - `GET /webhooks/whatsapp` — Meta verify handshake (`hub.challenge`, token
     from `META_WEBHOOK_VERIFY_TOKEN`).
   - `POST /webhooks/whatsapp` — HMAC-verified (`META_APP_SECRET`,
     `X-Hub-Signature-256`); dispatches: button replies → deterministic
     handlers, free text → wa_chat, statuses (delivered/read/failed) →
     structlog only. Idempotent by `message.id` (Redis SETNX, 24h TTL) —
     Meta redelivers.
2. **`backend/services/wa_service.py`**
   - `send_template(branch, to, template, components)` and
     `send_session_message(branch, to, text_or_interactive)` via httpx +
     tenacity. Uses the BRANCH's `wa_phone_number_id`; one Vachanam-level
     `META_ACCESS_TOKEN` (system user token, WABA-scoped).
   - Plan gate: silently no-op (log `wa_skipped_plan`) unless org plan ∈
     `WHATSAPP_PLANS` (new constant in `billing_math.py`, = {"clinic","multi"}).
3. **`backend/services/wa_chat.py`**
   - Free-text handler: Gemini (existing raw-REST pattern from support chat)
     with tools: `list_my_bookings`, `reschedule_booking`, `cancel_booking`,
     `clinic_location`, `clinic_faq`. Same guarded single-write semantics as
     voice (reuses booking service functions, NOT the LiveKit agent).
   - Out-of-scope intents (new booking, medical, complaints) → reply with
     clinic phone tap-to-call link.
   - Session window: replies only within Meta's 24h service window (free);
     outside it, nothing is sent unprompted.
4. **Schema (one migration)**
   - `branches.wa_phone_number_id` (nullable str) — set when clinic's number
     is linked; presence = WhatsApp active for branch.
   - `ratings` table: id, branch_id (FK CASCADE), token_id (FK SET NULL),
     patient_id (FK SET NULL), score 1–5, created_at. Unique per token.
   - `wa_messages` log table NOT built (YAGNI) — structlog covers debugging.

### Existing seams reused

- `MetaService.send_booking_confirmation / send_doctor_notification` —
  stub bodies replaced with wa_service calls; agent code untouched.
- Reminder job (`backend/jobs/`) — after the voice reminder dispatch, fire the
  WhatsApp reminder template for the same bookings (independent try/except).
- Attendance "Seen" transition (queue router) — enqueue rating ask; a small
  APScheduler job sends that evening (19:00 IST batch).
- Doctor-leave cascade (`cascade_cancel.py`) — WhatsApp ping alongside the
  rebook call.

## Message flows

### Outbound utility templates (pre-approved in Meta Business Manager, per language)

| Template | Trigger | Body (logistics only) | Buttons |
|---|---|---|---|
| `booking_confirm` | confirm_booking succeeds (voice) | clinic, doctor, date/time, token, address + Maps link | Reschedule · Cancel |
| `appt_reminder` | 30-min reminder job | doctor, time, token | Reschedule · Cancel |
| `rating_ask` | patient marked Seen (evening batch) | "how was your visit to {clinic}?" | 1★…5★ (quick replies) |
| `leave_rebook` | doctor marks leave | "Dr {name} unavailable {date}; we tried calling — reply to rebook" | Reschedule |

Templates authored in **Telugu + English first** (per-caller language known
from patient record); other languages follow after pilot. Telugu copy via the
humanizer flow (never hand-written).

### Inbound

- **Button: Reschedule** → offer next 3 available slots (existing availability
  code) as interactive list → patient picks → atomic reschedule (same function
  as voice tool) → confirmation text.
- **Button: Cancel** → confirm-cancel prompt → cancel via existing path.
- **Button: rating 1–5** → store in `ratings`; score ≤2 → owner email
  (existing Resend pattern; no message body in mail — RULE 9).
- **Free text** → wa_chat (Gemini). Unknown/out-of-scope → clinic tap-to-call.
- **Patients of non-WhatsApp branches / Starter plans**: webhook events for
  unlinked numbers are logged and dropped.

### Dashboard

- Ratings: average + count on Dashboard (existing card pattern), low-score
  flag. No new page.
- Settings: "WhatsApp" section shows linked-number status (read-only pilot;
  linking is concierge).

## Error handling

- Outbound: tenacity 3× exponential; final failure → `wa_send_failed`
  structlog + continue (RULE 4/8).
- Webhook: bad HMAC → 403; malformed → 200 + log (never make Meta retry-storm);
  handler exception → 200 + `wa_inbound_error` log, patient gets static
  "please call us at {clinic number}" if a reply context exists.
- Gemini failure → same static fallback line (RULE 8).
- Template REJECTED by Meta review → that flow silently stays off for the
  language; others unaffected.

## Costs

Utility ≈ ₹0.115–0.145/msg + 18% GST; service-window replies free. Full
journey (confirm + reminder + rating + a rebook ping) ≈ ₹0.40–0.60/booking —
absorbed in plan margin (no metering; revisit only if Meta repricing changes
the math). No infra additions (httpx + existing Redis/APScheduler).

## Prerequisites & rollout (Vinay actions flagged)

1. **Vinay (~1–2h one-time):** Meta Business Portfolio → developer app →
   WhatsApp product → WABA; system-user token; webhook URL + verify token +
   app secret into Render env. Exact click-by-click checklist delivered with
   implementation.
2. **Code ships fully tested behind config** — no WABA creds = every send
   no-ops exactly like today's stub; safe on prod from day one.
3. **Pilot clinic linking (concierge, ~15 min/clinic):** add clinic's number to
   WABA (OTP on clinic phone) + coexistence QR scan in their WhatsApp Business
   app; set `wa_phone_number_id` on the branch (admin route). Display name =
   clinic name.
4. **Caps until Meta business verification (GST docs — TD-038 timeline):**
   max 2 linked clinic numbers, 250 business-initiated conversations/day
   portfolio-wide. Verification lifts to 20 numbers / 1k+ conversations.
5. Templates submitted for Meta review (typically hours–2 days).

## Testing

- Unit: webhook HMAC verify (valid/invalid/replay), plan gate, branch
  resolution by phone_number_id (RULE 1/5 isolation — two branches, crossed
  events), template payload shape, rating uniqueness.
- Integration: button reschedule end-to-end against test DB (atomicity —
  reuse existing reschedule tests' fixtures), cancel path, rating store +
  low-score email (no body leak — RULE 9 guard), send no-op without creds.
- Gemini chat: prompt-contract tests (RULE 7 strings, tap-to-call fallback),
  tool-call routing with mocked Gemini.
- Manual pilot checklist: real number link, each template on a real phone,
  free-text reschedule in Telugu.

## Out of scope (explicit)

- New-booking via chat, media messages, group features, WhatsApp Flows forms,
  marketing/broadcast campaigns, per-clinic template customization, replacing
  voice reminder/rebook calls, embedded signup (until Meta verification),
  Starter-plan access, metering WhatsApp cost per clinic.

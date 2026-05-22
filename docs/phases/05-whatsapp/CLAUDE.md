# Phase 5 — WhatsApp ⬜ TODO

**Goal:** Meta Cloud API webhook running. Doctors text commands to the clinic's WhatsApp number and get responses. Patients can complete a full booking via WhatsApp without ever calling.

**Effort:** 3-4 days. **Prerequisites:** Phase 4 ✅. Meta WhatsApp Business account with permanent access token, `META_PHONE_NUMBER_ID`, `META_APP_SECRET`, `META_WEBHOOK_VERIFY_TOKEN`.

---

## Components

### 1. Meta service (HTTP client)
- [`backend/services/meta_service.py`](../../../backend/services/meta_service.py)
- `send_text_message(to, message, branch_id)` — POSTs to `graph.facebook.com/v20.0/{phone_id}/messages`, `@retry(stop_after_attempt(3))`
- `send_booking_confirmation(...)` — formatted patient confirmation
- `verify_webhook_signature(body: bytes, signature: str) -> bool` — `hmac.compare_digest("sha256=" + hexdigest, signature)`

### 2. Webhook router
- [`backend/routers/whatsapp.py`](../../../backend/routers/whatsapp.py)
- `GET /webhook/whatsapp` — Meta verify challenge
- `POST /webhook/whatsapp` — returns 200 in < 100ms, enqueues processing in `BackgroundTasks`
- **Branch identification:** `Branch.meta_phone_number_id == value.metadata.phone_number_id` (the receiver, NOT the sender). Never use sender phone.
- Inside background task: look up `Doctor.whatsapp_number == from_phone AND branch_id == <resolved>` → if hit, route to `DoctorCommandService`; else route to `WhatsAppAgent`

### 3. Doctor commands
- [`backend/services/doctor_commands.py`](../../../backend/services/doctor_commands.py)
- Intent parser: **Gemini primary → GPT-4o-mini fallback** (Rule 9 from root CLAUDE.md). Returns JSON `{intent, dates, token_count_to_add, confidence}`
- Intents: `LIST_APPOINTMENTS`, `CANCEL_DAY`, `ADD_TOKENS`, `UNKNOWN`
- Telugu/Hindi/code-mixed examples in prompt: "list today" / "ēḍu list" / "off tomorrow" / "rēpu ledu" / "add 5 tokens"
- On `CANCEL_DAY`: update token statuses to `cancelled_by_clinic`, delete Google Calendar events, fan out WA notifications to affected patients via `asyncio.gather`, then confirm to doctor

### 4. Patient state machine
- [`backend/services/whatsapp_agent.py`](../../../backend/services/whatsapp_agent.py)
- State stored in `WhatsAppSession` table (NOT on Patient — the schema has a dedicated table with `session_data: JSONB`)
- States: `GREETING → WAITING_NAME (optional) → WAITING_DOCTOR → WAITING_SLOT → CONFIRM → CONFIRMED`
- At any non-terminal state, cancel words (`cancel`, `vaddhu`, `nahi`) release any held Redis token and reset to `GREETING`
- Reuses `agent/tools/booking_tools.py` `assign_token()` and `confirm_booking()` — same atomicity guarantees as voice path

---

## Critical rules (carry-over from root CLAUDE.md)

| Rule | Where enforced |
|---|---|
| Branch identified from receiver number, never sender | `process_whatsapp_message()` |
| Webhook must return 200 within 5s (Meta requirement) | `BackgroundTasks` defer all work |
| Signature verified in production (`X-Hub-Signature-256`) | `verify_webhook_signature()` |
| Token assign via Redis INCR; DECR only on cancel/abandon | Inherited from booking_tools |
| Calendar success required, WA failure logged but doesn't block | Inherited from `confirm_booking` |
| Every WA send wrapped in try/except with structlog | `MetaService.send_*` |

---

## Setup required before code

1. Meta Business Manager → create WhatsApp Business Account
2. Add phone number → verify via SMS OTP
3. Generate permanent access token (System User → assign WABA → generate token, never expires)
4. In Meta dashboard: configure webhook URL → `https://<your-tunnel>/webhook/whatsapp`, verify token must match `META_WEBHOOK_VERIFY_TOKEN`
5. Subscribe to `messages` webhook event
6. For local dev: ngrok or cloudflared tunnel → `ngrok http 8000`
7. Insert one Branch row with `meta_phone_number_id` filled in (the numeric ID from Meta, NOT the human-readable +91 number)

---

## Acceptance criteria

```
[ ] GET /webhook/whatsapp?hub.mode=subscribe&hub.verify_token=<correct>&hub.challenge=1234 → 1234
[ ] POST /webhook/whatsapp returns 200 in <200ms (timed)
[ ] Send "list today" from doctor's WA → formatted schedule arrives
[ ] Send "off tomorrow" → patients receive WA cancel notice, doctor receives confirm, Token rows update to cancelled_by_clinic
[ ] Send first message from a new patient phone → "Mee pēru cheppandi" arrives
[ ] Complete a full booking via WA → row in tokens table with source='whatsapp', Redis counter incremented, WA confirmation arrives
[ ] Send "cancel" mid-booking → held Redis token released (DECR observed), state reset to GREETING
[ ] Send malformed message from doctor → help menu arrives
[ ] Signature verification: send fake X-Hub-Signature-256 in production mode → 401
```

---

## Files this phase creates

```
backend/services/meta_service.py
backend/services/doctor_commands.py
backend/services/whatsapp_agent.py
backend/services/token_service.py     (Redis release helper used by cancel paths)
backend/routers/whatsapp.py
tests/integration/test_whatsapp_doctor_cmds.py
tests/integration/test_whatsapp_patient_flow.py
```

Modifies `backend/main.py` to register the webhook router.

---

## What this phase does NOT do

- ❌ No EOD summaries (Phase 6 — those are scheduled jobs, but use MetaService built here)
- ❌ No outbound follow-up calls (Phase 6)
- ❌ No template messages (only freeform text inside the 24h customer service window — fine for MVP, templates needed for proactive outreach after 24h)

Move on to [Phase 6](../06-jobs-calendar/CLAUDE.md).

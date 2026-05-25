# Vachanam — Change Log

Session-by-session record of decisions, file changes, and direction shifts. Most recent at top. This is a running log — append new sessions; never edit old entries (they're historical record).

When you need to know "why was X done this way," check here. When you need to know "what was decided last week," check here. When STATUS.md says something is done, check here for the commits that did it.

Format per session:
- Date + topic
- Key decisions (with reasoning)
- Files created / modified / deleted
- Commits (hash + subject)
- Follow-ups for next session

---

## 2026-05-22 — Security & Compliance Spec

**Topic:** Brainstormed full security posture for MVP launch. Created design spec for Phase 4.5.

### Decisions

1. **Spec structure:** ONE cohesive Security & Compliance spec covering 8 areas (auth, session, rate limit, OWASP, audit, privacy, infra, breach). Reasoning: security works as a system — fragmenting it creates gaps.
2. **Posture target:** MVP-launch (not Scale-ready, not Enterprise). Reasoning: pre-launch with zero real patient data; over-engineering security now wastes time before product-market fit.
3. **Session policy:** 8h JWT hard timeout + 30min frontend idle timeout. Reasoning: covers a full clinic shift; idle timeout protects against momentary unattended device exposure.
4. **Rate limit strategy:** Layered (per-user + per-IP + per-endpoint) via slowapi + Redis. Per-endpoint overrides for `/auth/google` (5/min), `/api/create-order` (10/min), `/webhook/*` (1000/min), etc.
5. **Login methods:** Google OAuth only. Reasoning: no passwords to store, Google's 2FA inherited, no SMS-OTP SIM-swap risk.
6. **Audit log scope:** Sensitive actions only (login, token mark, doctor cancel, payments, admin views, security events). Append-only table. 7-year retention.
7. **Approach:** Defense-in-depth (Cloudflare edge + app middleware + audit log + route-level validation). Each layer assumes others might fail.
8. **No formal DPO for MVP** — Vinay is de facto DPO until SDF threshold (~50k users).
9. **No field-level PII encryption for MVP** — relying on Neon disk encryption + branch isolation + audit log.
10. **Phase 4.5 slotted** between Phase 4 (Backend Core) and Phase 5 (WhatsApp). Effort: 3-4 days.

### Files

- Created: `docs/superpowers/specs/2026-05-22-security-hardening-design.md` (~15 sections, ~900 lines, plain English)
- Created: `docs/CHANGELOG.md` (this file)
- Modified: `docs/STATUS.md` — added Phase 4.5; updated active phase pointer
- Modified: `docs/ROADMAP.md` — inserted Phase 4.5 between 4 and 5; renumbered nothing (4.5 is intentional)

### Commits

- *(pending — commit after spec self-review and user approval)*

### Follow-ups for next session

1. User reviews spec; revise if changes requested
2. Invoke `writing-plans` skill to break the spec into implementation tasks
3. Update STATUS.md and ROADMAP.md to mark Phase 4 next (security plan ready)

---

## 2026-05-22 (earlier) — Project Restructure: STATUS + ROADMAP + 10 Phase Docs

**Topic:** Project had drifted — 5 PHASE_N.md files at root, plans in docs/superpowers/plans/, progress in docs/vachanam-progress.md, Razorpay work jumped ahead of plan order. Restructured into a clean phase-based layout.

### Decisions

1. **New canonical structure:** `docs/STATUS.md` (truth source) + `docs/ROADMAP.md` (dependency map) + `docs/phases/NN-name/CLAUDE.md` (per-phase tasks).
2. **Old PHASE_N.md files at root** marked as historical reference only — not deleted (preserve history) but no longer authoritative.
3. **10 phases total** — 3 done (Foundation, Voice Agent, Razorpay Checkout), 7 to do (Backend Core, WhatsApp, Jobs+Calendar, Receptionist PWA, Owner+Admin Dashboards, Subscriptions+Onboarding, Deployment).
4. **Each phase gets its own CLAUDE.md** in a folder under `docs/phases/` — so opening that folder gives full context for working on that phase.
5. **Root CLAUDE.md** gets a "START HERE" pointer to STATUS.md and ROADMAP.md.

### Files

- Created: `docs/STATUS.md`, `docs/ROADMAP.md`
- Created: 10 phase folders each with CLAUDE.md (`01-foundation/` through `10-deployment/`)
- Modified: root `CLAUDE.md` — added "START EVERY SESSION HERE" block at the top

### Commits

- `3e4e698` — docs: restructure into STATUS.md + ROADMAP.md + 10 phase CLAUDE.md files

### Follow-ups

- Phase 4 (Backend Core) is next active phase
- Resolve pricing decision (Solo/Clinic/Multi from CLAUDE.md vs Starter/Growth/Unlimited from vachanam.in) before Phase 9

---

## 2026-05-22 (earlier) — Razorpay Standard Checkout (Test Mode)

**Topic:** Wired Razorpay Standard Web Checkout end-to-end. Mirror of vachanam.in serving as the test landing page. Verified order creation against live Razorpay test API.

### Decisions

1. **Lives in standalone `backend/payments_test_app.py`** because `backend/main.py` doesn't exist yet — Phase 4 will integrate it.
2. **`key_id` returned in `/api/create-order` response** so the frontend never needs `VITE_RAZORPAY_KEY_ID`. Secret never leaves server.
3. **Landing page** is 1:1 mirror of vachanam.in (947 lines, fonts: Outfit/Spectral/Pacifico, color `#006B6B`). Three pricing CTAs trigger Razorpay flow.
4. **Test mode quirk noted:** account is domestic-cards-only — `4111 1111 1111 1111` rejected because Razorpay treats it as international BIN. Owner action: enable International Payments in dashboard before live.
5. **Test mode quirk noted:** UPI tab shows QR-only; "Enter UPI ID" field hidden. Owner action: enable UPI Collect flow in dashboard.
6. **Starter plan price temporarily reduced to ₹99** for self-testing; restore before linking from real marketing.

### Files

- Created: `backend/routers/payments.py`, `backend/payments_test_app.py`, `backend/static/index.html`, `backend/static/razorpay-test.html`
- Modified: `.env` — filled `RAZORPAY_KEY_ID=rzp_test_Ss3Qe551bl3LRz`, `RAZORPAY_KEY_SECRET=clEoihnt7Q2OMTCZGJNvrSow`

### Commits

- `7f5a184` — feat(payments): Razorpay Standard Checkout end-to-end (test mode)

### Verified working

- Real Razorpay test orders created (e.g., `order_SsFxpRSIGK6my1`)
- Signature round-trip 200/400 (valid/invalid signatures)
- Amount validation 422 (< 100 paise)

### Follow-ups

- Phase 4 deletes `backend/payments_test_app.py`, mounts the router in `backend/main.py`
- Phase 9 swaps test keys for live `rzp_live_*` after Razorpay KYC

---

## 2026-05-22 (earlier) — Schema Gap Fix + Phase 2 Plan Draft + Infra Files

**Topic:** Identified gaps in the database schema vs what Phase 2 backend code would need; fixed schema; wrote Phase 2 plan (later superseded by docs/phases/04-backend-core/); created infra/ files.

### Decisions

1. **Schema fixes:**
   - Added `User` model (for JWT auth in Phase 4)
   - Added `Branch.meta_phone_number_id` (Meta's internal phone ID for webhook routing)
   - Added `Token.is_urgent`, `Token.confirmed_at`, `Token.attended_at`, `Token.marked_by_user_id`
   - Added `FollowupTask.what_to_ask`, `FollowupTask.channel`, `FollowupTask.scheduled_date`
   - Fixed token status enum: `confirmed | attended | no_show | cancelled_by_clinic` (removed `waiting`, which conflicted with Phase 2 code)
2. **Stale migration noted:** `alembic/versions/2fe8f201bc31_initial_schema.py` (2026-05-15) predates these schema additions. Phase 4 must regenerate.
3. **Infra files** for Fly.io and Render created.
4. **Phase 2 plan** drafted at `docs/superpowers/plans/2026-05-18-phase-2-backend.md` — superseded by `docs/phases/04-backend-core/CLAUDE.md`.

### Files

- Modified: `backend/models/schema.py`, `agent/tools/booking_tools.py` (status: `waiting` → `confirmed`)
- Created: `backend/requirements.txt`, `infra/Dockerfile.agent`, `infra/Dockerfile.backend`, `infra/fly.agent.toml`, `infra/render.yaml`, `docs/superpowers/plans/2026-05-18-phase-2-backend.md`

### Commits

- `96f6d92` — fix: schema gaps, Phase 2 plan, infra files

---

## 2026-05-17 — Vobiz Credentials Reset + Twilio Removal

**Topic:** User identified that Vobiz uses SIP trunk integration (not API key/secret/webhook). Replaced credentials across codebase. Removed Twilio entirely.

### Decisions

1. **Vobiz integration is SIP-based** — needs `VOBIZ_SIP_DOMAIN`, `VOBIZ_SIP_USERNAME`, `VOBIZ_SIP_PASSWORD`, `VOBIZ_DID_NUMBER` (from Vobiz console after creating a SIP trunk).
2. **Vobiz Partner API** is separate — uses `VOBIZ_PARTNER_AUTH_ID` and `VOBIZ_PARTNER_AUTH_TOKEN` for clinic-level DID provisioning.
3. **Twilio removed entirely** — not used. All Twilio references stripped from PHASE_5_PRODUCTION.md and CLAUDE.md.
4. **Uptime table updated** — added Vobiz row with retry + graceful "call back" fallback.

### Files

- Modified: `.env`, `.env.example`, `backend/config.py`, `CLAUDE.md`, `PHASE_5_PRODUCTION.md`

### Commits

- `ed5b333` — fix: replace Vobiz API key/secret/webhook with SIP credentials; remove Twilio entirely

---

## 2026-05-16 — Phase 1 Voice Agent Tests + Edge Cases

**Topic:** Wrote integration + edge-case tests for booking flow and concurrent tokens. Fixed multiple async/SQLAlchemy bugs discovered along the way.

### Decisions

1. **`asyncio_mode = auto` in pytest.ini** — replaces deprecated `event_loop` fixture override.
2. **Each concurrent coroutine** in `asyncio.gather` opens its own `async with AsyncSessionLocal()` — shared `AsyncSession` is NOT concurrent-safe.
3. **Capture SQLAlchemy attribute values into local vars** BEFORE exiting `async with` block — prevents `DetachedInstanceError`.
4. **`asyncio.to_thread`** for sync Gemini SDK calls inside async context — prevents event loop blocking.
5. **`new_message.content` guard** — may be list not str; isinstance check with fallback text extraction.
6. **Solo warning gate** — `solo_warning_sent: bool` flag in SessionState prevents repeated warnings after 230s.

### Files

- Created: `tests/conftest.py`, `tests/unit/test_tts_sanitizer.py`, `tests/unit/test_emergency.py`, `tests/integration/test_booking_flow.py`, `tests/edge_cases/test_concurrent_tokens.py`, `pytest.ini`
- Modified: `agent/agent.py`, `agent/session_state.py`

### Commits

- `eb8422b`, `6f366fe`, `3bb31c2`, `0fa5d00`, `eb140e2` — various fixes

---

## 2026-05-15 — Initial Implementation Sprint (Phase 0 + Phase 1)

**Topic:** Built Phase 0 (foundation) and Phase 1 (voice agent) from scratch using subagent-driven development.

### Decisions

1. **LLM order:** Gemini 2.5 Flash primary → GPT-4o-mini fallback (CLAUDE.md Rule 9).
2. **Pricing:** Solo ₹1,999 + ₹3/min · Clinic ₹7,999/2,100min · Multi ₹16,999/4,200min — set as canonical in CLAUDE.md.
3. **Emergency MVP:** keyword detect only → give `branch.emergency_contact`. No TYPE_1/TYPE_2 classification.
4. **Billing model:** anniversary cycle (not 1st of month).
5. **Trial:** 14 days / 1,000 min / no credit card.
6. **9 DB tables initially:** organizations, branches, doctors, patients, tokens, calls, followup_tasks, billing_cycles, whatsapp_sessions. (User table added 2026-05-22.)

### Files

- Created: full backend/ skeleton, full agent/ skeleton, alembic setup, docker-compose, .env structure, design doc at `docs/superpowers/specs/2026-05-15-vachanam-complete-design.md`, plan at `docs/superpowers/plans/2026-05-15-phase-0-1-voice-agent.md`

### Commits

- `a5370a0` (TTS sanitizer)
- `c163004` (emergency MVP)
- `ee794ef` (session_state)
- `ce0956f` (system prompt)
- `e12b919`, `901a71c` (booking tools)
- `e380486` (livekit agent)
- `3465978`, `b1248d7` (smaller fixes)

---

## How to update this file

When a session ends with material progress, add a new entry at the top:

```markdown
## YYYY-MM-DD — <Topic>

**Topic:** One-sentence summary.

### Decisions
1. Numbered list of decisions made. Include reasoning briefly.

### Files
- Created / Modified / Deleted lists.

### Commits
- `<hash>` — commit subject

### Follow-ups
- Next session should pick up X.
```

Never edit older entries — they are the historical record. If a past decision becomes wrong, add a new entry explaining why it changed and what was done.

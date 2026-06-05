# Vachanam — Status (single source of truth)

**Last updated:** 2026-06-05 (Phase 4.5 closed)
**Active phase:** Phase 1 — Voice Agent Core (next session starts here)
**Reliability posture:** MVP-launch (~99.4% uptime target). Phase 11 deferred until volume / outage / customer trigger fires. See [`docs/phases/11-reliability-hardening/CLAUDE.md`](phases/11-reliability-hardening/CLAUDE.md).

Read this at the start of every session. It tells you what's real, what's broken, what's next. If anything here contradicts an older doc, this file wins.

Also check [`docs/CHANGELOG.md`](CHANGELOG.md) for session-by-session decision history and [`docs/TECH_DEBT.md`](TECH_DEBT.md) for the shortcut ledger.

---

## ✅ PHASE 4.5 CLOSED — 2026-06-05

Security and Compliance sprint complete. 18 spec acceptance criteria: **14 GREEN + 3 MANUAL-VERIFICATION + 1 DEFERRED** (Shannon AI scan deferred to Phase 3 exit gate).

**Results summary:**
- JWT auth + jti revocation, fastapi-limiter rate limits, SecurityHeadersMiddleware, CORS exact-origin, audit_log table + @audit decorator with PII denylist, secrets-in-repo test, GitHub Actions CI + Dependabot, Cloudflare deploy runbook (Tasks 1-10, 14-16).
- Privacy policy + ToS + DPA + breach runbook + DSAR runbook (Tasks 11+13). /privacy /terms /dpa public HTML routes (Task 12).
- Voice agent Step 0 disclosure on call start (DPDP s.5 compliance).
- ZAP baseline CI workflow (PR + nightly) + 4 legal-routes coverage tests (Task 17a).
- Vobiz LiveKit provisioning script + agent_name fix (adjacent Phase 1+5 critical path).

**Test gate:** 155 passed + 1 skip. Zero regressions.

**Closed debts this sprint:** TD-015 (CI), TD-019 (FK ondelete), TD-022 (PII denylist). **Opened:** TD-026, TD-027, TD-028, TD-029.

---

## NEXT: Phase 1 — Voice Agent Core

Open `PHASE_1_VOICE_AGENT.md` (or `docs/phases/02-voice-agent/CLAUDE.md`). Voice agent code exists from Phase 2 (already built), but Phase 1 in the ROADMAP.md sense is foundational wiring that connects to telephony. Vobiz creds are in .env; provisioning script ready at `scripts/provision_vobiz_trunk.py`.

**Before starting Phase 1 next session:**
1. Read this STATUS.md (done)
2. Read `docs/ROADMAP.md` for phase order
3. Read `PHASE_1_VOICE_AGENT.md` for task list
4. Dispatch brainstormer for Phase 1 entry gate

### BLOCKERS open

- **Fly.io firewall ports** — Fly.io Mumbai VM needs ports 5060/UDP (SIP) + 10000-60000/UDP (RTP) opened for inbound calls. Phase 5/10 deploy prep.
- **Vinay: run `python scripts/provision_vobiz_trunk.py`** — creates SIP trunk + dispatch rule in LiveKit. Must complete before first live call. Can be done any time.
- **Anthropic API key for Shannon** — must be in `.env` as `ANTHROPIC_API_KEY` by end of Phase 3. Shannon scan is Phase 3 exit gate (TD-029).

---

## ✅ PHASE 4 COMPLETE — 2026-06-01

All 7 tasks shipped. `backend/main.py` boots, `/health` → 200, `/queue/{branch}/today` requires JWT, `POST /api/create-order` creates real Razorpay orders.

- ✅ Task 1: Alembic migration regenerated (`ffcf1134aa8f`) — 10 tables applied
- ✅ Task 2: `init_db()` helper added to `backend/database.py`
- ✅ Task 3: JWT auth middleware + branch_guard + admin guard
- ✅ Task 4: `POST /auth/google`, `GET /auth/me`, `POST /auth/logout`
- ✅ Task 5: `GET /queue/{branch_id}/today`, `PATCH .../attend`, `PATCH .../no-show` + 9 new tests (6 auth + 3 isolation)
- ✅ Task 6: `backend/main.py` with CORS, routers, landing mount, /health, prod-disabled /docs
- ✅ Task 7: Retired `backend/payments_test_app.py` (TD-002 closed)

Closed debts: TD-001, TD-002. Still open: TD-005, TD-014, TD-018, TD-020, TD-021.

---

## ✅ FIX SPRINT COMPLETE — 2026-05-29

Per [audit 2026-05-29](audits/2026-05-29-full-project-audit.md). Closed 7 tech debt items:

- ✅ TD-007 P0 — Replaced `_llm_with_fallback` with built-in `livekit.agents.llm.FallbackAdapter`
- ✅ TD-008 P0 — `session.disconnect()` → `session.aclose()`
- ✅ TD-009 P1 — Added `_solo_cap_watchdog` background polling task
- ✅ TD-010 P2 — Concurrency test N=5 → N=100 + limit-boundary variant
- ✅ TD-011 P3 — conftest uses `settings.redis_url`
- ✅ TD-012 P2 — conftest pre-flushes Redis
- ✅ TD-013 P2 — 8 obsolete docs archived to `docs/_legacy/`

Voice agent ready for Phase 5 telephony enablement. Test suite below tester.md bar fixed.

## Open tech debt (carry into Phase 4 / 4.5 / 9 / 10)

**P1 (high):**
- TD-015 — No CI / secret-scan job → Phase 4.5

**P2 (medium):**
- TD-014 — Dockerfiles run as root → fix before Phase 10
- TD-018 — Initial migration has zero non-unique indexes → 2nd migration before Phase 5
- TD-020 — Pre-cached greeting WAV not yet published via LiveKit track-publish API → Phase 10
- TD-021 — STT confidence threshold (Layer A) not wired (LiveKit abstraction); Layer B active → Phase 10

**P3 (low):**
- TD-005 — Romanized `padipōyāḍu` vs Telugu script → verify in Phase 10 acceptance
- TD-019 — FKs default to NO ACTION ondelete (should be explicit RESTRICT/CASCADE) → Phase 4.5

**Recently closed (2026-05-29 + 2026-06-01):** TD-003 + TD-004 (pricing), TD-006 (test suite green), TD-016 + TD-017 (event-loop bugs), TD-001 (Alembic migration regenerated), **TD-002 (payments_test_app deleted; main.py mounts payments router)**

## Test baseline (verified 2026-06-01)

`pytest tests/ -v` against Docker Postgres 16 + Redis 7 + Python 3.14 → **77/77 pass** (60 unit + 4 integration + 5 edge-case + 8 security-prep). Baseline locked.

---

## What works right now (verified end-to-end)

| Component | Status | Where |
|---|---|---|
| Voice agent: TTS sanitizer | 11/11 tests pass | [agent/services/tts_sanitizer.py](../agent/services/tts_sanitizer.py) |
| Voice agent: emergency keyword detection | 12/12 tests pass | [agent/services/emergency.py](../agent/services/emergency.py) |
| Voice agent: session state, system prompt | manual review | [agent/session_state.py](../agent/session_state.py), [agent/prompts/system_prompt.py](../agent/prompts/system_prompt.py) |
| Voice agent: 4 booking tools (route, check, assign, confirm) | unit logic verified | [agent/tools/booking_tools.py](../agent/tools/booking_tools.py) |
| Voice agent: LiveKit entrypoint (Solo cap, emergency, token rollback) | code review | [agent/agent.py](../agent/agent.py) |
| Razorpay Standard Checkout | order_id created against live Razorpay test API, signature verify works | [backend/routers/payments.py](../backend/routers/payments.py) |
| Razorpay test landing page | renders, all 3 plan buttons trigger checkout | [backend/static/index.html](../backend/static/index.html) (mirror of vachanam.in) |
| DB schema (10 tables: Org, Branch, Doctor, Patient, Token, Call, FollowupTask, BillingCycle, WhatsAppSession, User) | imports without error | [backend/models/schema.py](../backend/models/schema.py) |
| Alembic configured (loads URL from settings) | env.py works | [alembic/env.py](../alembic/env.py) |
| docker-compose for Postgres + Redis | starts cleanly | [docker-compose.yml](../docker-compose.yml) |

---

## What's broken or unverified

| Issue | Severity | Fix-where |
|---|---|---|
| `alembic/versions/2fe8f201bc31_initial_schema.py` was generated 2026-05-15, **before** the schema additions on 2026-05-22 (User model, Branch.meta_phone_number_id, Token timestamps, FollowupTask channel). Needs a follow-up migration. | HIGH | Phase 4 task |
| Tests have not been executed in this session — Docker likely not running, DB not migrated | HIGH | Phase 4 first acceptance check |
| `backend/main.py` does not exist. Razorpay router lives only inside the standalone `payments_test_app.py` | HIGH | Phase 4 main task |
| Razorpay test mode merchant account rejects `4111 1111 1111 1111` ("domestic cards only") and UPI tab only shows QR (collect flow disabled) | LOW (test mode quirk) | Phase 9 — enable in dashboard before live mode |
| Pricing mismatch: root `CLAUDE.md` says Solo ₹1,999 / Clinic ₹7,999 / Multi ₹16,999. Live site (`vachanam.in`) shows Starter ₹6,999 / Growth ₹9,999 / Unlimited ₹14,999. The landing page mirror uses the **live site** tiers, the master spec uses the original. | DECISION-NEEDED | Resolve before Phase 9 — see "Decisions needed" below |
| The Sarvam STT romanization of `padipōyāḍu` in emergency keywords may not match real STT output (could need Telugu script form `పడిపోయాడు`) | LOW | Phase 10 — verify with real call |

---

## Active confusion to clean up

| Confusion | Action |
|---|---|
| Multiple competing plan docs: `PHASE_0_*.md` ... `PHASE_5_*.md` at root, `docs/superpowers/plans/*.md`, `docs/vachanam-progress.md`, and now `docs/phases/`. | **NEW canonical:** `docs/phases/`. Old docs kept as historical reference only. |
| `backend/static/index.html` is a 1:1 mirror of vachanam.in serving as a Razorpay test target. It is NOT the receptionist app or the owner dashboard — those are separate frontends built in Phases 7 and 8. | Marked in [docs/phases/03-razorpay-checkout/CLAUDE.md](phases/03-razorpay-checkout/CLAUDE.md) |
| `backend/payments_test_app.py` is a temporary standalone FastAPI that hosts only the Razorpay router. It exists because `backend/main.py` doesn't yet. Phase 4 deletes it. | Marked in [docs/phases/04-backend-core/CLAUDE.md](phases/04-backend-core/CLAUDE.md) |

---

## Decisions needed (block work in later phases)

1. **Pricing tiers final answer.** Original SaaS pricing (Solo / Clinic / Multi) vs live-site pricing (Starter / Growth / Unlimited)? Whichever is canonical must be reflected in CLAUDE.md, the landing page button amounts, and the three `RAZORPAY_PLAN_*_ID` env vars.
2. **Live Razorpay account activation.** Production needs `rzp_live_*` keys, KYC, and the 3 subscription plans created in dashboard. Owner action.
3. ~~**Meta WhatsApp Business account.**~~ **DEFERRED to MVP2** (client decision 2026-06-03). Not needed for MVP1 launch. Will be required when Phase 5 WhatsApp work begins in MVP2.
4. **Vobiz SIP trunk.** Need actual `VOBIZ_SIP_DOMAIN`, `VOBIZ_SIP_USERNAME`, `VOBIZ_SIP_PASSWORD`, `VOBIZ_DID_NUMBER` from the Vobiz console before the voice agent can answer real calls.

---

## Phase map (full detail in `docs/ROADMAP.md`)

```
Phase 1   Foundation              ✅ DONE
Phase 2   Voice agent core        ✅ DONE  (tests pass, manual call needs Phases 4 + 9 to dial-in)
Phase 3   Razorpay checkout       ✅ DONE  (test mode, standalone)
Phase 4   Backend core            ✅ DONE
Phase 4.5 Security & compliance   ✅ DONE  (closed 2026-06-05)
Phase 1*  Voice agent telephony   🔨 NEXT  ← active phase (connect to Vobiz + LiveKit live)
Phase 5   WhatsApp                🅿️ DEFERRED-MVP2 (client decision 2026-06-03)
Phase 6   Jobs + Calendar         ⬜ (MVP1 REDUCED: Calendar + token expiry only; WA jobs → MVP2)
Phase 7   Receptionist PWA        ⬜
Phase 8   Owner + Admin dashboards ⬜
Phase 9   Subscriptions + Onboarding ⬜ (email reminders, not WA; WA → MVP2)
Phase 10  Deployment              ⬜ (no Meta WA infra needed for MVP1)
🔒 Shannon scan gate — must pass 0 critical before Phase 4 onboarding work begins
```

---

## What "next session" looks like

Open `PHASE_1_VOICE_AGENT.md` and execute its task list. Phase 1 connects the voice agent to live telephony via Vobiz SIP trunk + LiveKit on Fly.io Mumbai. By the end of Phase 1 you have:

- LiveKit server running on Fly.io Mumbai with SIP trunk configured
- Vobiz DID forwarding to LiveKit via `scripts/provision_vobiz_trunk.py`
- Voice agent answering real inbound calls in Telugu
- End-to-end test: phone call -> AI answers -> token booked

Then Phase 6 (Jobs + Calendar) begins.

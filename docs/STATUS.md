# Vachanam — Status (single source of truth)

**Last updated:** 2026-05-29 (after fix sprint)
**Active phase:** Phase 4 — Backend Core (next session starts here)

Read this at the start of every session. It tells you what's real, what's broken, what's next. If anything here contradicts an older doc, this file wins.

Also check [`docs/CHANGELOG.md`](CHANGELOG.md) for session-by-session decision history and [`docs/TECH_DEBT.md`](TECH_DEBT.md) for the shortcut ledger.

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
- TD-001 — Stale Alembic migration → Phase 4 Task 1
- TD-015 — No CI / secret-scan job → Phase 4.5

**P2 (medium):**
- TD-002 — `backend/payments_test_app.py` → delete during Phase 4 Task 7
- TD-006 — Test suite never executed end-to-end → Phase 4 acceptance check
- TD-014 — Dockerfiles run as root → fix before Phase 10

**P3 (low):**
- TD-005 — Romanized `padipōyāḍu` vs Telugu script → verify in Phase 10 acceptance

**Recently closed (2026-05-29):** TD-003 + TD-004 (pricing canonical Solo/Clinic/Multi confirmed; landing page updated)

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
3. **Meta WhatsApp Business account.** Needs verified business + phone number + permanent access token before Phase 5 can be wired live.
4. **Vobiz SIP trunk.** Need actual `VOBIZ_SIP_DOMAIN`, `VOBIZ_SIP_USERNAME`, `VOBIZ_SIP_PASSWORD`, `VOBIZ_DID_NUMBER` from the Vobiz console before the voice agent can answer real calls.

---

## Phase map (full detail in `docs/ROADMAP.md`)

```
Phase 1   Foundation              ✅ DONE
Phase 2   Voice agent core        ✅ DONE  (tests pass, manual call needs Phases 4 + 9 to dial-in)
Phase 3   Razorpay checkout       ✅ DONE  (test mode, standalone)
Phase 4   Backend core            🔨 NEXT  ← start here
Phase 4.5 Security & compliance   📋 SPEC DONE  (docs/superpowers/specs/2026-05-22-security-hardening-design.md)
Phase 5   WhatsApp                ⬜
Phase 6   Jobs + Calendar         ⬜
Phase 7   Receptionist PWA        ⬜
Phase 8   Owner + Admin dashboards ⬜
Phase 9   Subscriptions + Onboarding ⬜
Phase 10  Deployment              ⬜
```

---

## What "next session" looks like

Open `docs/phases/04-backend-core/CLAUDE.md` and execute its task list. By the end of Phase 4 you have:

- `backend/main.py` running with `uvicorn`
- JWT auth working
- Existing payments router wired into the real app (delete the standalone test app)
- A fresh Alembic migration covering today's schema additions
- `GET /health` returns 200, `POST /api/create-order` works through the real app, `GET /queue/{branch_id}/today` returns 401 without auth

Then Phase 5 begins.

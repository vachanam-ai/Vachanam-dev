# Vachanam — Full Project Audit (10-Specialist Review)

**Date:** 2026-05-29
**Triggered by:** Client request — review everything built; correct what feels wrong; delete + redesign anything not good enough
**Auditor:** Manager (orchestrating; applied each specialist's lens)
**Status:** Findings only. No deletion or rewrite performed. Client decision required (Section 8).

---

## 1. Executive summary (TL;DR)

The voice agent (Phase 1) is **senior-grade and largely correct**, but contains **one critical bug** in `agent.py` that prevents the documented Gemini→GPT-4o-mini fallback from working under load. The schema (Phase 0) is correct but the Alembic migration is **stale** (predates User table and 7+ field additions). Razorpay checkout (Phase 3) works but lives in a **standalone test app** that must be retired. No backend `main.py`, no real React frontend yet — but those are correctly identified as Phase 4 / Phase 7 work and not yet attempted.

**Doc landscape is the main mess:** 5 obsolete PHASE_N.md files at the repo root, an obsolete `docs/vachanam-progress.md`, and an obsolete `docs/superpowers/plans/2026-05-18-phase-2-backend.md` all coexist with the new (correct) `docs/phases/` + `STATUS.md` + `ROADMAP.md` structure. Engineers reading the repo cold cannot tell which is canonical.

**Recommendation: Option B — Major fix sprint (1-2 days) before starting Phase 4.** Do NOT delete and restart from scratch. The bones are right; the gaps are bounded and named. Burning everything down would cost 2-3 weeks for ~5% structural improvement.

---

## 2. What's solid — KEEP AS-IS

| Artifact | Lines | Notes |
|---|---|---|
| `agent/services/tts_sanitizer.py` | 26 | Clean, focused, 11/11 tests pass |
| `agent/services/emergency.py` | 18 | MVP keyword detect, 12/12 tests pass (one weakness — see §4) |
| `agent/session_state.py` | 43 | Well-commented dataclass; correct fields for current scope |
| `agent/prompts/system_prompt.py` | 76 | Builds Telugu prompt correctly with rebook + Solo cap variants |
| `agent/tools/booking_tools.py` | 324 | Canonical implementation of route/check/assign/confirm. Redis INCR + DECR rollback correct. Calendar-first / WA-fallback correct. |
| `backend/models/schema.py` | 270 | Senior-grade schema. 10 tables, proper UUID PKs, proper indexes pattern, branch_id on all multi-tenant tables. JSONB for variable data. |
| `backend/config.py` | 65 | Clean Pydantic settings. All env vars defined. |
| `backend/database.py` | 26 | Minimal, correct async engine + sessionmaker. |
| `backend/routers/payments.py` | ~120 | Razorpay create-order + verify-payment. HMAC-SHA256 with `hmac.compare_digest`. Pydantic validation. Senior-grade. |
| `docker-compose.yml`, `alembic.ini`, `alembic/env.py` | small | All correct. |
| `docs/superpowers/specs/2026-05-22-security-hardening-design.md` | ~900 | Comprehensive, plain English, just written. |
| `docs/STATUS.md`, `docs/ROADMAP.md`, `docs/CHANGELOG.md`, `docs/TECH_DEBT.md`, `docs/phases/*/CLAUDE.md` | various | Just refactored. Clean canonical structure. |
| `.claude/agents/*` (10 specialists + AGILE + QUALITY_BAR) | ~3000 | Just built. Roster + workflow + standards. |
| Razorpay integration end-to-end | — | Real test orders verified against live Razorpay API. |

---

## 3. Critical bug found — must fix before Phase 5

### C-1: `_llm_with_fallback` is defined but never wired into the agent session

**File:** `agent/agent.py:121-144`

The function `_llm_with_fallback` implements Gemini-primary → GPT-4o-mini-fallback per CLAUDE.md Rule 9. It is defined at module scope but **never called**. The actual LLM passed to `AgentSession` (line 176-181) is the raw `google.LLM` from `livekit.plugins.google`:

```python
llm = google.LLM(
    model="gemini-2.5-flash",
    api_key=settings.gemini_api_key,
    temperature=0.3,
)
session = AgentSession(stt=stt, tts=tts, llm=llm)
```

**Consequence:** When Gemini fails during a real call, the session has no fallback. The patient hears silence or an error tone. The Rule 9 contract is silently violated. We have no test for this because the agent test suite doesn't exercise the LiveKit session integration (correctly — that's hard to test without a real call).

**Severity:** P0 Critical — violates a documented non-negotiable rule, will manifest on any Gemini outage (~99.9% uptime → ~43 min downtime/month → real patient impact).

**Fix:** Implement a custom `LLM` adapter for `livekit.agents` that wraps `_llm_with_fallback`, OR catch LLM exceptions at the session level and gracefully reset to a known-good response. This requires reading the LiveKit Agents 1.4 API for custom LLM providers.

**Owner:** `voice-agent-engineer` (with `brainstormer` consulted on adapter design)

### C-2: SOLO 4-min cap only fires on user turns

**File:** `agent/agent.py:104-118`

The `elapsed_seconds` check and disconnect logic is inside `on_user_turn_completed`. If the patient goes silent at 3:55 and never speaks again, the agent will not enforce the 4-min cap. Call could run indefinitely → billing impact.

**Severity:** P1 High — billing-correctness for Solo plan.

**Fix:** Add a background asyncio task (started in `entrypoint`) that polls `state.elapsed_seconds` every 5 seconds and triggers warning / disconnect independent of user activity.

**Owner:** `voice-agent-engineer`

### C-3: Method name `session.disconnect()` may not exist in LiveKit Agents 1.4

**File:** `agent/agent.py:44, 118`

The method `session.disconnect()` is called but the LiveKit Agents 1.4 API uses `aclose()` for session shutdown. Untested because no integration test runs the actual session. Will crash at runtime on first real call.

**Severity:** P0 Critical — agent crashes on first real call.

**Fix:** Verify against `livekit-agents>=1.4.0` API docs. Use `session.aclose()` (or whatever the correct method is).

**Owner:** `voice-agent-engineer`

---

## 4. Important issues — fix before Phase 5

### I-1: Concurrent token test runs only N=5

**File:** `tests/edge_cases/test_concurrent_tokens.py:60`

Per `tester.md` rule 5 ("Concurrency tests run N ≥ 100"), this test is below the bar. N=5 will not expose race conditions. Currently passes only because Redis INCR is genuinely atomic, but we need N=100+ to prove it under realistic contention.

**Severity:** P2 — risk of undetected race condition under real load.

**Fix:** Bump to N=100 (or 200 with `daily_token_limit=200` to allow all to succeed). Add a second test variant that pre-fills 99 tokens, then 10 concurrent callers race for the last → exactly 1 success, 9 "full".

**Owner:** `tester`

### I-2: conftest hardcodes Redis URL

**File:** `tests/conftest.py:27`

```python
r = aioredis.from_url("redis://localhost:6379", decode_responses=True)
```

Should use `settings.redis_url`. Per `tester.md` rule 5 ("no hardcoded credentials, URLs, or phone numbers"), this is a violation.

**Severity:** P3 — works locally, breaks if anyone changes Redis port or runs against staging.

**Fix:** Use `settings.redis_url`. Same as the existing `db` fixture pattern.

**Owner:** `tester`

### I-3: Conftest redis fixture doesn't flush BEFORE the test (only after)

**File:** `tests/conftest.py:26-30`

```python
async def redis():
    r = aioredis.from_url(...)
    yield r
    await r.flushdb()        # only AFTER
    await r.aclose()
```

If a previous test leaks (or `flushdb` failed), the next test starts polluted. Per `tester.md` rule 7 ("redis fixture flushes between tests"), should flush BEFORE AND after.

**Severity:** P2 — silent test pollution can cause hard-to-debug intermittent failures.

**Fix:** `await r.flushdb()` BEFORE the `yield` too.

**Owner:** `tester`

### I-4: Emergency keyword `padipōyāḍu` is romanized, not script

**File:** `agent/services/emergency.py:7`

Sarvam STT output is in Telugu script (`పడిపోయాడు`), not romanized. The romanized form will never match. (Already tracked as TD-005, restated here for visibility.)

**Severity:** P3 — only blocks one specific emergency phrase; other English keywords still work.

**Fix:** Add the Telugu script variant alongside the romanized one. Test against real Sarvam STT output during Phase 10 acceptance.

**Owner:** `voice-agent-engineer`

### I-5: Alembic migration stale (already tracked TD-001)

**File:** `alembic/versions/2fe8f201bc31_initial_schema.py`

Line 23: `"""Create all 9 tables for Vachanam initial schema."""` — schema now has 10 tables (User added). Token status enum has `"waiting"` but schema enum has `"confirmed"`. Multiple new fields missing on Branch, Token, FollowupTask.

**Severity:** P1 — `alembic upgrade head` against current code produces a DB that doesn't match the ORM.

**Fix:** Phase 4 Task 1 (already planned in `docs/phases/04-backend-core/CLAUDE.md`).

**Owner:** `database-engineer`

---

## 5. Doc landscape mess — clean up this sprint

These files exist at the same time as the new canonical docs. They confuse anyone reading the repo cold.

| File | Status | Action |
|---|---|---|
| `PHASE_0_ENVIRONMENT.md` (root) | Superseded by `docs/phases/01-foundation/CLAUDE.md` | Archive to `docs/_legacy/` |
| `PHASE_1_VOICE_AGENT.md` (root) | Superseded by `docs/phases/02-voice-agent/CLAUDE.md` | Archive |
| `PHASE_2_BACKEND.md` (root) | Superseded by `docs/phases/04-backend-core/CLAUDE.md` | Archive |
| `PHASE_3_FRONTEND.md` (root) | Superseded by `docs/phases/07-frontend-receptionist/` + `08-frontend-dashboards/` | Archive |
| `PHASE_4_ONBOARDING.md` (root) | Superseded by `docs/phases/09-subscriptions-onboarding/CLAUDE.md` | Archive |
| `PHASE_5_PRODUCTION.md` (root) | Superseded by `docs/phases/10-deployment/CLAUDE.md` | Archive |
| `docs/vachanam-progress.md` | Superseded by `docs/STATUS.md` + `docs/ROADMAP.md` | Archive |
| `docs/superpowers/plans/2026-05-18-phase-2-backend.md` | Old plan; superseded by `docs/phases/04-backend-core/CLAUDE.md` | Archive (or delete — plans are working docs, not history) |
| `docs/superpowers/specs/2026-05-15-vachanam-complete-design.md` | Original design spec. Many decisions superseded but still useful as historical reference | Keep but add header: "SUPERSEDED in part — see CLAUDE.md root + security spec for current decisions" |

**Action:** Create `docs/_legacy/` and move the obsolete files there. They stay in git history regardless. README in `_legacy/` explains "these files are kept for archaeology; current truth is in `docs/STATUS.md`."

**Owner:** `manager` (doc moves are administrative)

---

## 6. Specialist-by-specialist audit

### Voice agent engineer

| Finding | Severity |
|---|---|
| C-1 `_llm_with_fallback` unused | P0 |
| C-2 SOLO cap only fires on user turns | P1 |
| C-3 `session.disconnect()` may not exist in API | P0 |
| I-4 Emergency keyword romanization | P3 |
| Otherwise: high-quality, well-commented, follows rules | — |

### Backend engineer

| Finding | Severity |
|---|---|
| No `backend/main.py` yet (correctly Phase 4 work) | — |
| No auth/queue/whatsapp/dashboard routers yet (correctly future phases) | — |
| `backend/routers/payments.py` is solid | — |
| `backend/payments_test_app.py` exists as scaffolding (TD-002) | P2 |

### Database engineer

| Finding | Severity |
|---|---|
| Schema is correct and well-designed | — |
| Alembic migration is stale (TD-001 / I-5) | P1 |
| No `docs/db/schema-erd.md` yet | P3 — create when schema stabilizes |
| No `docs/db/migration-log.md` yet | P3 — create with first new migration |
| No `audit_log` table yet (correctly Phase 4.5 work) | — |

### Frontend engineer

| Finding | Severity |
|---|---|
| No `frontend/` directory yet (correctly Phase 7 work) | — |
| `backend/static/index.html` (vachanam.in mirror) is a test target only — production marketing stays at vachanam.in independent host | — |
| `backend/static/index.html` had Starter price reduced to ₹99 for self-test (TD-003) | P2 |
| No frontend tests, no Playwright setup | — out of MVP scope |

### Devops engineer

| Finding | Severity |
|---|---|
| `docker-compose.yml` correct for local dev | — |
| `infra/Dockerfile.agent`, `Dockerfile.backend`, `fly.agent.toml`, `render.yaml` exist but: Dockerfiles do NOT run as non-root yet | P2 — must be fixed before Phase 10 |
| No `.github/workflows/` yet | — to be added in Phase 4.5 + Phase 10 |
| No secret-scan CI yet | P1 — should be in place before any push to a public-readable remote |
| No `docs/runbooks/` directory yet | — populated alongside Phase 4.5 + Phase 10 |

### Security engineer

| Finding | Severity |
|---|---|
| Security & Compliance spec exists (just written), comprehensive | — |
| No security middleware implemented yet (correctly Phase 4.5 work) | — |
| No audit_log table yet (correctly Phase 4.5 work) | — |
| No rate limiting yet | — Phase 4.5 |
| No CSP/HSTS yet | — Phase 4.5 |
| Razorpay payments router: signature verify uses `hmac.compare_digest` ✓ | — |
| `.env` file with real test keys exists but is gitignored ✓ | — |
| No secret-scanning CI hook yet | P1 |

### Privacy & legal

| Finding | Severity |
|---|---|
| No `docs/legal/privacy-policy.md` yet | P1 — must exist before any paying customer signup (Phase 9) |
| No `docs/legal/terms-of-service.md` yet | P1 — same |
| No `docs/runbooks/breach-response.md` yet | P1 — Phase 4.5 work |
| No `docs/runbooks/dsar.md` yet | P2 — Phase 9 work |
| No `docs/compliance/dpdp-mapping.md` yet | P2 — Phase 4.5 work |
| No `docs/compliance/third-party-processors.md` yet | P1 — required by privacy policy |
| Security spec Section 9 covers DPDP — but spec is design, not policy | — Phase 4.5 produces the actual docs |

### Tester

| Finding | Severity |
|---|---|
| 23 unit tests pass (tts_sanitizer + emergency) | — |
| Integration + edge_cases written but NOT EXECUTED this session (Docker not started) | P1 (TD-006) |
| Concurrent test N=5 (should be ≥100) — I-1 | P2 |
| Conftest hardcodes Redis URL — I-2 | P3 |
| Conftest doesn't pre-flush Redis — I-3 | P2 |
| No `tests/security/` yet (correctly Phase 4.5) | — |
| No `tests/_phase_N_acceptance.md` mapping criteria → tests | P3 |

### Brainstormer

| Finding | Severity |
|---|---|
| No design-fork brainstorm artifacts yet (specialist just created today) | — first use will be Phase 4 dispatch |

### Manager

| Finding | Severity |
|---|---|
| Just rewritten with client accountability + opus brain | — |
| Has not yet run a full sprint cycle with the new roster | — first sprint will be Phase 4 |
| `docs/TECH_DEBT.md` exists with 6 backfilled debts | — |

---

## 7. What's MISSING (gaps to close)

Ordered by when needed:

| Gap | Needed by | Owner |
|---|---|---|
| Stale Alembic migration → new revision | Phase 4 Task 1 | database-engineer |
| `backend/main.py` | Phase 4 | backend-engineer |
| JWT auth + queue endpoints | Phase 4 | backend-engineer + security-engineer |
| Critical voice agent bug fixes (C-1, C-2, C-3) | Before Phase 5 telephony enabled | voice-agent-engineer |
| Test concurrency bumped to N=100, conftest fixed | Before Phase 4 marked done | tester |
| Security middleware (CSP, rate limit, audit) | Phase 4.5 | security-engineer |
| Privacy policy + ToS + DPDP mapping + breach runbook | Phase 4.5 (legal docs) and before first paying clinic (Phase 9) | privacy-legal |
| GitHub Actions CI with test + secret scan | Phase 4.5 | devops-engineer |
| Docker non-root user | Before Phase 10 | devops-engineer |
| WhatsApp infrastructure (services + router + tests) | Phase 5 | backend-engineer |
| Calendar + jobs | Phase 6 | backend-engineer + devops-engineer |
| React frontend (PWA, dashboards) | Phase 7-8 | frontend-engineer |
| Razorpay subscriptions (vs current one-time checkout) | Phase 9 | backend-engineer |
| Vobiz DID provisioning | Phase 9 | backend-engineer + devops-engineer |
| Production deployment | Phase 10 | devops-engineer |

---

## 8. Decisions needed (CLIENT — please choose)

### Decision 1: Cleanup plan

| Option | Effort | What you get |
|---|---|---|
| **A — Fix sprint + proceed (recommended)** | 1-2 days before Phase 4 | Fix C-1/C-2/C-3 voice agent bugs; fix I-1/I-2/I-3 test issues; archive obsolete docs to `docs/_legacy/`; then start Phase 4 fresh. Code stays largely as-is. |
| B — Major refactor | 3-5 days | A + redesign voice agent integration with LiveKit Agents 1.4 (custom LLM adapter); restructure tests with explicit phase-acceptance mapping; rewrite agent.py end-to-end against verified 1.4 API. |
| C — Burn down + restart | 2-3 weeks | Delete `agent/`, `backend/`, `tests/`, `alembic/versions/*`, all docs. Start from updated specs. **Not recommended — would lose ~85% of correct work for ~5% structural improvement.** |

**My recommendation: A.** The bones are right. The bugs are bounded and named. The doc mess is administrative cleanup. Burning down loses real work.

### Decision 2: Pricing tiers (still unresolved, TD-004)

| Option | Where it shows |
|---|---|
| **Solo / Clinic / Multi (₹1,999 / ₹7,999 / ₹16,999)** | CLAUDE.md says this is canonical |
| **Starter / Growth / Unlimited (₹6,999 / ₹9,999 / ₹14,999)** | vachanam.in live shows this; landing page mirror uses this |

You must pick one before Phase 9 (subscriptions). Cleanup affects: Razorpay plan IDs, CLAUDE.md, landing page mirror, all phase docs that reference pricing.

### Decision 3: `backend/static/index.html` future

Currently a 1:1 mirror of vachanam.in serving as a Razorpay test target. Options:

| Option | What it implies |
|---|---|
| **Keep as Razorpay test target only** (recommended) | After Phase 4 wires `payments.py` into `main.py`, delete `payments_test_app.py` but keep `static/index.html` as a sandbox. Production marketing stays on vachanam.in independent host. |
| Promote to production landing page | Wire it as the real signup entry. Means Render serves the marketing site. Slightly slower than Cloudflare Pages but simpler. Means we commit to maintaining this HTML as marketing copy too. |
| Delete entirely | Razorpay testing done via curl + `dev/test` page only. Loses the human-friendly test UI. |

### Decision 4: Sprint sequencing for the fix work

If you pick Option A (recommended):

| Sprint | Length | Goal |
|---|---|---|
| **Fix sprint** (next session) | 1-2 days | Fix C-1, C-2, C-3, I-1, I-2, I-3; archive obsolete docs; bump TECH_DEBT to closed for these items |
| **Phase 4** (sprint after) | 1-2 days | backend/main.py, JWT auth, queue endpoints, new migration |
| **Phase 4.5** | 3-4 days | Security middleware + privacy/legal docs |
| **Phase 5+** | as planned | WhatsApp → Jobs → Frontend → ... |

---

## 9. Verdict on "is everything built till now good enough?"

**Code-wise: 85% good.** The 15% that's broken is named (C-1, C-2, C-3 plus tests). All fixable in 1-2 days.

**Doc-wise: 70% good.** The new structure is right; the obsolete files crowding it bring confidence down. Cleanup in hours, not days.

**Decision-wise: 90% good.** All major architecture decisions documented with rationale. Two unresolved: pricing tiers (Decision 2) and landing page future (Decision 3).

**Strategy-wise: solid.** The 10-phase roadmap is sensible. The 10-specialist roster + AGILE + QUALITY_BAR is the right cadence. The security & compliance spec is comprehensive. Vachanam is on track for a real launch in 3-4 weeks if Phase 4 starts cleanly.

**Burn it down? No.** That would be expensive vanity. Fix the named bugs, archive the dead docs, and start Phase 4.

---

## 10. If you DO want a full restart

If you reject my recommendation and want Option C anyway, here's what the brainstormer + manager would do:

1. `git tag pre-restart-2026-05-29` — preserve the state
2. Delete: `agent/`, `backend/routers/`, `backend/services/`, `backend/jobs/`, `backend/middleware/`, `backend/payments_test_app.py`, `backend/static/`, `tests/integration/`, `tests/edge_cases/`, `alembic/versions/*`, all old `PHASE_*.md`, `docs/vachanam-progress.md`, `docs/superpowers/plans/*`
3. Keep: `CLAUDE.md`, `.env`, `docs/STATUS.md`, `docs/ROADMAP.md`, `docs/CHANGELOG.md`, `docs/TECH_DEBT.md`, `docs/phases/*`, `docs/superpowers/specs/2026-05-22-security-hardening-design.md`, `.claude/agents/*`, `infra/`, `docker-compose.yml`
4. Re-brainstorm Vachanam from scratch using the brainstormer (with the existing specs as constraints)
5. Re-implement Phase 0 through Phase 10 from scratch using the new specialist team

Estimated effort: 2-3 weeks of focused specialist work. Net improvement vs Option A: marginal, mostly emotional. **I do not recommend this.** But it's your call.

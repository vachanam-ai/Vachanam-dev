# Vachanam — Technical Debt Ledger

Every shortcut taken in this project is logged here with severity and a payback plan. Manager updates this on every sprint. If a row sits with no payback for too long, it gets escalated to the client.

A debt row stays until paid down. When paid down, move it to the "Paid down" section at the bottom with the date and the commit hash.

---

## Severity guide

| Level | What it means | Payback window |
|---|---|---|
| **P0 Critical** | Data leak risk, payment correctness risk, compliance risk | Same sprint, no exceptions |
| **P1 High** | Production-affecting if not addressed before scale | Within 2 sprints |
| **P2 Medium** | Affects developer velocity / maintenance cost | Within the current phase |
| **P3 Low** | Cosmetic / convenience | When touching the code anyway |

---

## Open debt

| ID | Severity | Date added | Owner specialist | Description | Why it was taken | Payback plan | Target sprint |
|---|---|---|---|---|---|---|---|
| ~~TD-001~~ | ~~P1~~ | ~~2026-05-22~~ | ~~database-engineer~~ | **CLOSED 2026-06-01 — see Paid down section.** Deleted broken 2fe8f201bc31 (dual-create enum bug + stale schema). Generated single clean migration ffcf1134aa8f covering all 10 tables. Applied. 29/29 tests still green. | | | |
| TD-018 | P2 | 2026-06-01 | database-engineer | Initial migration `ffcf1134aa8f` has ZERO non-unique indexes. Per database-engineer.md: every FK needs index (Postgres doesn't auto-index FKs); compound `(branch_id, date)` on tokens; `(branch_id, doctor_id, date)` for doctor schedule queries; `(phone)` on Patient; `(whatsapp_number)` on Doctor. UNIQUE constraints already auto-index 5 columns (users.email, users.google_sub, branches.meta_phone_number_id, branches.whatsapp_number, organizations.owner_email). | Autogen default doesn't emit indexes unless explicitly declared in schema.py via `index=True` or `Index(...)` | Add second migration `phase4_indexes` with `op.create_index` for all FKs + compound query patterns. Update schema.py mapped_column with `index=True` for tracked columns. | Phase 4 — before Phase 5 (when query volume grows) |
| TD-019 | P3 | 2026-06-01 | database-engineer | All FK constraints in initial migration default to NO ACTION ondelete. Per database-engineer.md rule 10: cascade behavior must be explicit (CASCADE or RESTRICT). Default NO ACTION ≈ RESTRICT but not portable. | Autogen doesn't infer ondelete; relationships in schema.py don't specify it | Update schema.py FK declarations to specify ondelete (CASCADE for child rows like Token deletes when Branch deleted = NEVER; mostly RESTRICT to force explicit data deletion path). Second migration to ALTER constraints. | Phase 4.5 (during data-lifecycle / DPDP review) |
| TD-002 | P2 | 2026-05-22 | backend-engineer | `backend/payments_test_app.py` standalone FastAPI exists only because `backend/main.py` doesn't yet | Razorpay integration shipped before backend core | Delete during Phase 4 Task 7 when main.py is built and includes payments router | Phase 4 |
| ~~TD-003~~ | ~~P2~~ | ~~2026-05-22~~ | ~~backend-engineer~~ | **CLOSED 2026-05-29 — see Paid down section.** Resolved as part of TD-004 — pricing now canonical Solo ₹1,999 + ₹3/min. | | | |
| ~~TD-004~~ | ~~P1~~ | ~~2026-05-22~~ | ~~manager~~ | **CLOSED 2026-05-29 — see Paid down section.** Client decided: canonical CLAUDE.md pricing (Solo/Clinic/Multi). Landing page UI mirror updated. | | | |
| TD-005 | P3 | 2026-05-22 | voice-agent-engineer | Emergency keyword `padipōyāḍu` (romanized Telugu) may not match Sarvam STT output (could need Telugu script `పడిపోయాడు`) | Easier to read in code; STT output not yet verified with real call | Verify on first real call in Phase 10; add Telugu script alongside if needed | Phase 10 |
| ~~TD-006~~ | ~~P2~~ | ~~2026-05-22~~ | ~~tester~~ | **CLOSED 2026-05-29 — see Paid down section.** Full pytest suite executed; 29/29 pass after TD-016 + TD-017 fixes. | | | |
| ~~TD-016~~ | ~~P1~~ | ~~2026-05-29~~ | ~~voice-agent-engineer~~ | **CLOSED 2026-05-29 — see Paid down section.** Replaced module-level `redis_client` in booking_tools with `async with _redis()` per call. | | | |
| ~~TD-017~~ | ~~P1~~ | ~~2026-05-29~~ | ~~database-engineer~~ | **CLOSED 2026-05-29 — see Paid down section.** Added `backend.database.engine.dispose()` before/after each test in conftest. | | | |
| ~~TD-007~~ | ~~P0~~ | ~~2026-05-29~~ | ~~voice-agent-engineer~~ | **CLOSED 2026-05-29 — see Paid down section.** Replaced `_llm_with_fallback` with built-in `livekit.agents.llm.FallbackAdapter`. | | | |
| ~~TD-008~~ | ~~P0~~ | ~~2026-05-29~~ | ~~voice-agent-engineer~~ | **CLOSED 2026-05-29 — see Paid down section.** Replaced `session.disconnect()` with `session.aclose()` (2 sites). | | | |
| ~~TD-009~~ | ~~P1~~ | ~~2026-05-29~~ | ~~voice-agent-engineer~~ | **CLOSED 2026-05-29 — see Paid down section.** Added `_solo_cap_watchdog` background polling task. | | | |
| ~~TD-010~~ | ~~P2~~ | ~~2026-05-29~~ | ~~tester~~ | **CLOSED 2026-05-29 — see Paid down section.** N=100 + boundary variant. | | | |
| ~~TD-011~~ | ~~P3~~ | ~~2026-05-29~~ | ~~tester~~ | **CLOSED 2026-05-29 — see Paid down section.** conftest uses `settings.redis_url`. | | | |
| ~~TD-012~~ | ~~P2~~ | ~~2026-05-29~~ | ~~tester~~ | **CLOSED 2026-05-29 — see Paid down section.** conftest pre-flushes Redis. | | | |
| ~~TD-013~~ | ~~P2~~ | ~~2026-05-29~~ | ~~manager~~ | **CLOSED 2026-05-29 — see Paid down section.** 8 obsolete docs moved to `docs/_legacy/`. | | | |
| TD-014 | P2 | 2026-05-29 | devops-engineer | `infra/Dockerfile.agent` and `infra/Dockerfile.backend` do NOT use a non-root user. `QUALITY_BAR.md` requires `USER app` after install. | Initial Dockerfiles were MVP; rule introduced after | Add `RUN groupadd -r app && useradd -r -g app ...` + `COPY --chown=app:app` + `USER app` to both Dockerfiles | Before Phase 10 |
| TD-015 | P1 | 2026-05-29 | devops-engineer | No GitHub Actions CI workflow yet — no automated test on PR, no secret-scan job. Secrets could land in repo undetected. | Not yet built | Add `.github/workflows/ci.yml` with pytest + secret-scan job | Phase 4.5 |

---

## Paid down

| ID | Severity | Date paid | Commit | Resolution |
|---|---|---|---|---|
| TD-007 | P0 | 2026-05-29 | *(pending)* | Replaced raw `google.LLM` with `livekit.agents.llm.FallbackAdapter([Gemini, GPT-4o-mini])` in `agent/agent.py`. Built-in adapter handles failover transparently per call. Removed unused `_llm_with_fallback` function. |
| TD-008 | P0 | 2026-05-29 | *(pending)* | Replaced `session.disconnect()` with `session.aclose()` in `agent/agent.py` (2 call sites). LiveKit Agents 1.4 uses `aclose()` for session shutdown. |
| TD-009 | P1 | 2026-05-29 | *(pending)* | Added `_solo_cap_watchdog` background asyncio task in `agent/agent.py`. Polls every 5s, fires warning at SOLO_CAP_SECONDS-10 (gated by `solo_warning_sent`), closes session at SOLO_CAP_SECONDS. Cancelled in entrypoint's `finally` block on session end. Removed duplicate logic from `on_user_turn_completed`. |
| TD-010 | P2 | 2026-05-29 | *(pending)* | Rewrote `tests/edge_cases/test_concurrent_tokens.py`. Now: (1) `test_100_concurrent_callers_get_unique_sequential_tokens` runs N=100 with `daily_token_limit=200`; (2) `test_10_concurrent_callers_at_limit_boundary` pre-fills 99, races 10 for the last, asserts exactly 1 success + 9 `full` + Redis counter exactly 100 (rollbacks verified). |
| TD-011 | P3 | 2026-05-29 | *(pending)* | Replaced hardcoded `"redis://localhost:6379"` with `settings.redis_url` in `tests/conftest.py`. |
| TD-012 | P2 | 2026-05-29 | *(pending)* | Added `await r.flushdb()` BEFORE the `yield` in conftest's redis fixture. Prevents previous-test pollution. |
| TD-013 | P2 | 2026-05-29 | *(pending)* | Moved 8 obsolete docs to `docs/_legacy/`: PHASE_0..5_*.md (root), `docs/vachanam-progress.md`, `docs/superpowers/plans/2026-05-18-phase-2-backend.md`. Added `docs/_legacy/README.md` explaining archaeology-only purpose. |
| TD-004 | P1 | 2026-05-29 | *(pending)* | Client decision: keep canonical pricing from CLAUDE.md (Solo ₹1,999 + ₹3/min, Clinic ₹7,999 flat / 2,100 min, Multi ₹16,999 flat / 4,200 min / 2 branches). Reject vachanam.in live Starter/Growth/Unlimited tier names + amounts. |
| TD-003 | P2 | 2026-05-29 | *(pending)* | Resolved by TD-004 closure. Landing page mirror pricing section rewritten with canonical Solo/Clinic/Multi cards (₹1,999 / ₹7,999 / ₹16,999). data-amount attributes updated to 199900 / 799900 / 1699900 paise. Core UI (color #006B6B teal, Outfit/Spectral/Pacifico fonts, layout structure) unchanged per client instruction. |
| TD-006 | P2 | 2026-05-29 | *(pending)* | Full pytest suite executed against Docker Postgres 16 + Redis 7. 29/29 tests pass after TD-016 + TD-017 fixes (3 prior failures were event-loop binding bugs in production code, exposed by test runner — not test code defects). Baseline established for Phase 4. |
| TD-016 | P1 | 2026-05-29 | *(pending)* | Discovered during Phase 4 prep test run. Module-level `redis_client = aioredis.from_url(...)` in `agent/tools/booking_tools.py` bound to first event loop at import. Failed with `RuntimeError: Event loop is closed` on subsequent test loops AND would fail on uvicorn worker restart in production. Fixed: replaced with `_redis()` factory + `async with _redis() as r:` per call. Cost: ~1-2ms per Redis op on localhost. Production-safe under any loop topology. |
| TD-017 | P1 | 2026-05-29 | *(pending)* | Discovered during Phase 4 prep test run. Module-level `engine` in `backend/database.py` pooled connections across pytest-asyncio test loops (mode=auto). Pool reuse triggered `_check_closed` on stale loops. Fixed: conftest's `db` fixture now calls `backend.database.engine.dispose()` before AND after each test, forcing a fresh pool per loop. Test-only change — production keeps the pooled engine. |
| TD-001 | P1 | 2026-06-01 | *(pending)* | Deleted broken `alembic/versions/2fe8f201bc31_initial_schema.py` (dual-create ENUM bug — explicit `enum.create()` + implicit `Enum()` column creation → "type already exists" failure). Generated single clean migration `ffcf1134aa8f_initial_schema_with_user_table.py` via autogen against current schema.py. Applied to fresh DB. All 10 tables present (users, branches, doctors, patients, tokens, calls, followup_tasks, billing_cycles, whatsapp_sessions, organizations) + alembic_version. 29/29 tests still pass after migration applied. Deleted-and-regenerated is acceptable here because the old migration never successfully ran in production. |

When closing a future row, append here with this format:
```
| TD-XXX | severity | date paid | commit hash | how it was resolved |
```

---

## Rules

- Every shortcut creates a row here — no silent shortcuts
- Every row has an owner specialist and target sprint
- Manager reviews open debt every sprint planning
- P0 debt that misses its sprint = escalation to client
- P1 debt overdue twice = escalation
- Paid-down rows are NEVER deleted — they're moved to the bottom for historical record
- When a row blocks a feature, link the feature task to this row

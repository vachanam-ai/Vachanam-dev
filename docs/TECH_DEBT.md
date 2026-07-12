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
| TD-027 | P1 | 2026-06-15 (upd 06-16) | voice-agent-engineer | **smallest.ai voice CLONING endpoint unresolved** (TTS + catalog now fully live). UPDATE 06-16: the new pay-as-you-go key works — `POST /waves/v1/tts` returns 200 audio (agent TTS unblocked) and the 8 landing language samples were generated from it. BUT the SDK's `add_voice`/`delete_voice`/`get_cloned_voices` still hit the retired `lightning-large` path (410), and the current "Create a Voice Clone" REST path is NOT discoverable: probed ~35 candidate paths (all 404 except the 410 lightning-large), latest SDK 4.4.7 has no v3.1 clone method, and the docs' JS nav is unreadable by the fetcher. So the Settings "Clone a voice" button currently returns a clean 502. | Couldn't pin the live clone endpoint by docs or probing; TTS + the per-language default voices were the priority and are done. | Get the exact Create/List/Delete clone endpoint from app.smallest.ai (open the dashboard's voice-clone feature with the browser Network tab → copy the request URL), OR wait for a smallestai SDK release whose clone path moves to lightning-v3.1. Then point smallest_voice.clone_voice/delete at it + one real end-to-end clone test. Cloning is a sell-feature (clinics opt in), not launch-blocking — default voices cover every clinic. | Before promoting voice cloning to clinics |
| TD-026 | P2 | 2026-06-15 | voice-agent-engineer | **Vobiz sub-account AUTO-provisioning deferred.** The credential SEAM is built (per-branch encrypted SIP creds + per-clinic outbound trunk + `/branches/{id}/telephony` + resolver with global fallback; FIXLOG #126). What's NOT built: programmatically creating a Vobiz sub-account + assigning a DID at onboarding, and auto-creating the per-clinic LiveKit outbound trunk. Creds are entered MANUALLY for now. | Vinay unsure whether the Vobiz partner API exposes sub-account create + DID assign (2026-06-15); building the seam first works either way and unblocks manual setup. | Confirm Vobiz partner-API capability. If yes: build an onboarding provisioner (create sub-account → assign DID → create LiveKit outbound trunk → store creds via the existing encrypted columns) + a Settings UI section. If manual-only: write a short onboarding runbook + a Settings form for the 5 fields. Also set `FIELD_ENCRYPTION_KEY` in prod (dev derives from jwt_secret). | When concurrency bites OR before onboarding clinic #2 on a second Vobiz account |
| ~~TD-001~~ | ~~P1~~ | ~~2026-05-22~~ | ~~database-engineer~~ | **CLOSED 2026-06-01 — see Paid down section.** Deleted broken 2fe8f201bc31 (dual-create enum bug + stale schema). Generated single clean migration ffcf1134aa8f covering all 10 tables. Applied. 29/29 tests still green. | | | |
| TD-018 | P2 | 2026-06-01 (scope reduced 2026-06-02) | database-engineer | Initial migration `ffcf1134aa8f` has ZERO non-unique indexes. Per database-engineer.md: every FK needs index (Postgres doesn't auto-index FKs). UNIQUE constraints already auto-index 5 columns (users.email, users.google_sub, branches.meta_phone_number_id, branches.whatsapp_number, organizations.owner_email). **SCOPE (revised 2026-06-02 per client decision):** Phase 4.5 ships **FK-only indexes** — `op.create_index` on every FK column across all 10 tables. Compound indexes — `(branch_id, date)` on tokens, `(branch_id, doctor_id, date)` for doctor schedule queries, `(phone)` on Patient, `(whatsapp_number)` on Doctor — are **DEFERRED to Phase 5** pending real `EXPLAIN ANALYZE` evidence from non-trivial query volume. We are not adding speculative compound indexes without measured query plans (write-cost is non-zero; evidence-based indexing only). | Autogen default doesn't emit indexes unless explicitly declared in schema.py via `index=True` or `Index(...)`. Brainstormer Pick 3 (Phase 4.5 plan validation, 2026-06-02) recommended evidence-based compound indexing; client accepted. | **Phase 4.5 (this sprint):** add second migration `phase45_fk_indexes` with `op.create_index` for every FK column. Update schema.py mapped_column with `index=True` for those columns. **Phase 5:** capture `EXPLAIN ANALYZE` from real query patterns (token lookup by branch+date, doctor schedule by branch+doctor+date, patient lookup by phone, doctor lookup by whatsapp_number). For each query where sequential scan > 100ms or > 10× index scan, add the targeted compound index in a separate migration with the evidence quoted in the migration docstring. | FK-only: Phase 4.5. Compound: Phase 7 or Phase 9 (evidence-gated; originally Phase 5, moved since WA deferred to MVP2 per client decision 2026-06-03). |
| ~~TD-019~~ | — | — | — | **CLOSED 2026-07-12 — explicit ondelete on all FKs (35 declarations in schema.py, applied in phase45 migration)** | | | |
| ~~TD-002~~ | ~~P2~~ | ~~2026-05-22~~ | ~~backend-engineer~~ | **CLOSED 2026-06-01 — see Paid down section.** Deleted `backend/payments_test_app.py`. Payments router now mounted in `backend/main.py` at `/api`. |  |  |  |
| ~~TD-003~~ | ~~P2~~ | ~~2026-05-22~~ | ~~backend-engineer~~ | **CLOSED 2026-05-29 — see Paid down section.** Resolved as part of TD-004 — pricing now canonical Solo ₹1,999 + ₹3/min. | | | |
| ~~TD-004~~ | ~~P1~~ | ~~2026-05-22~~ | ~~manager~~ | **CLOSED 2026-05-29 — see Paid down section.** Client decided: canonical CLAUDE.md pricing (Solo/Clinic/Multi). Landing page UI mirror updated. | | | |
| ~~TD-005~~ | — | — | — | **CLOSED 2026-07-12 — emergency keyword detection REMOVED entirely 2026-06-07 (intent-based transfer only) — row obsolete** | | | |
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
| ~~TD-014~~ | — | — | — | **CLOSED 2026-07-12 — was already closed 2026-06-13 (FIXLOG #93, non-root Dockerfiles) — open-table row was stale** | | | |
| ~~TD-015~~ | ~~P1~~ | ~~2026-05-29~~ | ~~devops-engineer~~ | **CLOSED 2026-06-04 — see Paid down section.** `.github/workflows/ci.yml` added with two jobs: `test` (Python 3.11 + PG16 + Redis7 + pytest) and `secret-scan` (gitleaks OSS full-history scan). `.gitleaks.toml` added (allowlist for test fixtures). `.github/dependabot.yml` added (weekly pip + npm + actions updates). |  |  |  |
| ~~TD-020~~ | — | — | — | **CLOSED 2026-07-12 — superseded by welcome-audio pre-synth + raw-track play (voice overhaul #264-271) — instant first audio** | | | |
| ~~TD-021~~ | — | — | — | **CLOSED 2026-07-12 — obsolete: Soniox primary STT + judge pipeline replaced the confidence-threshold design** | | | |
| ~~TD-022~~ | — | — | — | **CLOSED 2026-07-12 — PII denylist enforced in audit_service (module docstring: 'TD-022 closed') + tests** | | | |
| TD-023 | P2 | 2026-06-02 | devops-engineer | audit_log table is currently writable + deletable by the vachanam_app role (default Postgres GRANT-all-to-owner). Spec §8.4 + migration-log explicitly state append-only enforcement requires GRANT INSERT, SELECT ON audit_log TO vachanam_app + REVOKE UPDATE, DELETE ON audit_log FROM vachanam_app, deferred to Phase 10 prod-init. Forward-compat verified by security-engineer review 2026-06-02 — no follow-up migration needed, just role-permission SQL in prod-init script. Risk: if Phase 10 ships without these GRANT/REVOKE lines, a compromised app token can rewrite audit history. | Cleanest separation of concerns — schema is created by migration as same-role admin, role-permission scoping is a prod-init concern, not a schema concern. Local dev uses single role (vachanam) for simplicity. | Phase 10 prod-init script (`scripts/prod_db_init.sql` or equivalent) must include: `GRANT INSERT, SELECT ON audit_log TO vachanam_app; REVOKE UPDATE, DELETE ON audit_log FROM vachanam_app;` AND `REVOKE TRUNCATE ON audit_log FROM vachanam_app;`. Plus tests: integration test in Phase 10 attempts UPDATE/DELETE via vachanam_app role, asserts permission-denied. | Phase 10 (prod cutover) |
| ~~TD-024~~ | — | — | — | **CLOSED 2026-07-12 — superseded: paid conversion path is the PWA checkout (#309), not the static page; static page dies at live-keys go-live** | | | |
| ~~TD-025~~ | — | — | — | **CLOSED 2026-07-12 — CLOSED 2026-07-12 (#344): except narrowed to (SQLAlchemyError, OSError, RuntimeError)** | | | |
| ~~TD-026~~ | — | — | — | **CLOSED 2026-07-12 — user.login.failure audit row present in auth.py (spec §8.2 email-allowed)** | | | |
| ~~TD-027~~ | — | — | — | **CLOSED 2026-07-12 — backend/jobs/data_retention.py exists + runs daily in prod (cited by data-handling doc)** | | | |
| ~~TD-028~~ | — | — | — | **CLOSED 2026-07-12 — CLOSED 2026-07-12 (#344): scripts/dsar.py built (export/correct/delete/withdraw, branch-scoped, shared erasure path, audited) + 5 tests** | | | |
| ~~TD-030~~ | — | — | — | **CLOSED 2026-07-12 — obsolete with TD-033: emergency keywords removed 2026-06-07; CLAUDE.md RULE 7 already states intent-based transfer** | | | |
| ~~TD-029~~ | — | — | — | **CLOSED 2026-07-12 — superseded by the 2026-07-11 adversarial audits (#312 full-codebase security-hacker sweep + #313 OWASP mapping): IDOR/JWT/HMAC/business-logic all covered, 0 critical** | | | |
| TD-031 | P3 | 2026-06-06 | voice-agent-engineer | **Migrate voice stack from LiveKit to Pipecat (deferred, conditional).** Spike 2026-06-06 confirmed Pipecat = better conceptual fit (built for 1-on-1 voice agents vs LiveKit's multi-participant focus) but rewrite = 4-6 days, same cost, must write own concurrency supervisor. Path A chosen (strip current LiveKit stack). | LiveKit stack already in production path; rewrite cost-neutral but burns 4-6 days with no feature gain. Conditional on LiveKit-specific pain emerging post-launch. | Trigger condition: if LiveKit-specific pain emerges in production (SIP bridge issues, concurrency dispatch limits, plugin lock-in). Payback: ~4-6 days to rewrite agent.py + tools on Pipecat pipeline API. Preserve booking_tools business logic, Redis token assignment, branch isolation, audit_log. Swap transport from LiveKit SIP to WebSocket via Vobiz X-Pipecat repo or via Daily.co intermediary. | Post-launch (conditional — only if trigger fires) |
| ~~TD-032~~ | — | — | — | **CLOSED 2026-07-12 — moot: conftest rewritten with the prod fuse (#324); tests never run alembic — schema via create_all per test DB** | | | |
| ~~TD-033~~ | — | — | — | **CLOSED 2026-07-12 — obsolete: RULE 7 rewritten during the judgment-based CLAUDE.md rework; current text matches implementation** | | | |
| TD-034 | P2 | 2026-06-06 | devops-engineer | **Local DID per clinic at Phase 4 onboarding.** Testing uses out-of-region (Karnataka) no-commit Vobiz DID. At clinic onboarding, patients calling a non-local area code may perceive as spam, hurting answer rates. Per `project-vobiz-region-test` memory. | Vobiz test DID was the only available no-commit option for development; production clinics need local-region DIDs for patient trust. | At Phase 4 onboarding flow build, add step to provision local Vobiz DID matching clinic's city (Hyderabad/Mumbai/Bangalore etc.) with 6-month commitment accepted. Bake commit cost into Solo/Clinic/Multi plan pricing (already covers Rs 1,000/mo DID line per CLAUDE.md cost table). | Phase 9 (clinic onboarding build) |
| TD-035 | P2 | 2026-06-06 | devops-engineer | **`provision_vobiz_trunk.py` blind to credential rotation.** When Vobiz trunk creds rotated (new SIP domain + username + password from a new no-commit DID), provision script's name-based idempotency skipped Steps 1-3 ("already exists"), leaving LiveKit trunks with stale Vobiz creds. Manual teardown required (delete old LiveKit trunks via livekit-api SDK, then re-run). Captured in DISPATCHES.md 2026-06-06. | Provision script designed for single-use setup, not credential rotation. Idempotency check uses trunk name only, not address or auth fields. | Enhance provision_vobiz_trunk.py Steps 1-2 to compare existing trunk's `address` + `auth_username` against current .env values. If mismatch, delete + recreate. Or: add explicit `--force-recreate` CLI flag. ~30 LOC. Add unit tests. | Phase 9 (clinic onboarding build) |
| ~~TD-036~~ | — | — | — | **CLOSED 2026-07-12 — CLOSED 2026-07-12 (#344): scripts/check_vobiz_did_ready.py built (KYC / provider / recycled-DID checks, loud per-check diagnostics)** | | | |
| ~~TD-037~~ | — | — | — | **CLOSED 2026-07-12 — CLOSED 2026-07-12 (#344): python-jose → PyJWT everywhere (3 backend files + 29 test files); pip-audit ignore for PYSEC-2026-1325 removed from security.yml** | | | |

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
| TD-002 | P2 | 2026-06-01 | *(pending)* | Deleted `backend/payments_test_app.py`. Standalone scaffolding no longer needed — `backend/main.py` now mounts the payments router at `/api`, serves the landing page at `/`, and serves the dev test page at `/dev/test` (404 in production). Smoke-tested: `POST /api/create-order` returns real Razorpay order. |

| TD-015 | P1 | 2026-06-04 | `76cd7c3` | Created `.github/workflows/ci.yml` (test job: Python 3.11 + PG16 + Redis7 + alembic + pytest; secret-scan job: gitleaks OSS full-history). Created `.gitleaks.toml` (default OSS ruleset + allowlist for test fixture phones, ci.yml test secrets, .env.example). Created `.github/dependabot.yml` (weekly pip backend + agent, npm frontend future-proof, github-actions). |

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

| TD-019 | P1 | 2026-06-12 | *(pending)* | Razorpay verify-payment validates the HMAC but persists NOTHING (no BillingCycle row, no org status change) and razorpay_webhook_secret has no webhook route (bug-bounty B10). A 'verified' payment does not activate/extend any subscription. Must be wired in the Razorpay billing phase BEFORE first paying clinic. |

| TD-020 | P2 | 2026-06-13 | *(pending)* | Bug-bounty L7: patient-initiated cancels are stored as `cancelled_by_clinic` (the only cancel status). Analytics conflates clinic leave-cancellations with patient changes of mind, and a self-cancelling patient could later hear rebook-call framing. Needs a `cancelled_by_patient` enum value (Alembic enum migration) + agent + analytics split. Deferred from round-2 (enum migration out of batch scope). |
| TD-021 | P2 | 2026-06-13 | *(pending)* | Bug-bounty L11: walk-in `is_urgent` neither bypasses the daily cap nor captures `emergency_reason` (schema says it should). PRODUCT DECISION NEEDED (Vinay): does an urgent walk-in bypass a full queue, given the no-triage rule (memory: clinic-scope, intent-based transfer)? Flag currently stored-only. Either wire the bypass + reason capture or remove the flag from the UI. |
| TD-022 | P3 | 2026-06-13 | *(pending)* | Bug-bounty L10: `if True:` wrapper block in agent.py entrypoint (cosmetic de-indent of ~250 lines, deferred — risky churn for zero behavior change). Unused `included_minutes` import already removed. |
| TD-023 | P2 | 2026-06-13 | *(pending)* | Bug-bounty T3: changing a doctor's google_calendar_id orphans the old recurring hours event and the upsert PATCH fails (404) on the new calendar. doctors._maybe_upsert_recurring_cal_event must delete/clear the old event id when the calendar changes before re-inserting. Deferred from round-3 (recurring-sync rework). |
| TD-024 | P3 | 2026-06-13 | *(pending)* | Bug-bounty T7: solo-cap watchdog hard-deletes the room even mid-confirm — an in-flight booking at the 4-min cap could be dropped. Add a short grace when an unconfirmed hold exists. Low — solo calls rarely hit the cap mid-confirm. |
| TD-025 | P2 | 2026-06-13 | *(pending)* | Bug-bounty T9: /api/create-order and /api/verify-payment are unauthenticated and trust body org_id. Harmless while persistence is a no-op (TD-019) but becomes activation-spoofing once billing wires in. Require auth + derive org_id server-side as part of the Razorpay billing phase (do together with TD-019). |
| TD-026 | P2 | 2026-06-13 | *(pending)* | Bug-bounty F9: token-doctor capacity is enforced on the monotonic Redis number-minter (issued count), which is never decremented on cancel. Same-day cancellation of a CONFIRMED token frees a real seat but the clinic still reports "full" until the daily key expires. A correct fix needs a SEPARATE decrement-on-cancel occupancy counter (Redis or DB confirmed-count gate) while the number-minter stays monotonic — must not weaken the no-overbook invariant (confirm_booking's confirmed>=limit hard check). Attempted in r4, reverted: gating assign on db_confirmed alone let in-flight holds mint unbounded numbers and broke the capacity tests. Key resets daily so impact is bounded. |
| TD-027 | P2 | 2026-06-13 | *(pending)* | Bug-bounty F5/F6/F11 (durability cluster): (F5) slot doctors have NO DB unique/exclusion backstop for occupancy — only Redis + a TOCTOU confirmed-count guard protect a slot; add a partial unique on (branch,doctor,date,appointment_time) when max_concurrent_per_slot==1, or SELECT…FOR UPDATE on the slot count. (F6) call minutes are written only in the shutdown callback (best-effort) — a killed worker loses the metering that drives overage billing + hard-block; persist a row at call start and finalize at end, or reconcile from LiveKit/Vobiz CDRs. (F11) after a Redis eviction the number-minter is reseeded from confirmed COUNT, so a previously-cancelled number can be reissued — seed from a durable high-water mark max(token_number) over all statuses instead. |

## Paid down — 2026-06-13 (go-live sprint)

- **TD-019 + TD-025 (P1/P2) — Razorpay billing + payments auth: CLOSED.** create-order is auth-gated + plan-priced + server-sets order notes; new `/api/razorpay-webhook` (HMAC-verified) is the authoritative activation → flips org to active + writes a paid BillingCycle, idempotent on razorpay_payment_id. FIXLOG #88. NOTE: requires the live `RAZORPAY_PLAN_*_ID` + `razorpay_webhook_secret` env + the webhook URL registered in the Razorpay dashboard (owner action — see GO_LIVE.md).
- **TD-027 (P2) — call-metering durability: CLOSED (F5/F6 portion).** CallLog now written at call start and finalized at end; `finalize_stale_calls` reconciles crash-stranded rows. FIXLOG #89. (The F5 slot-occupancy DB backstop and F11 high-water seed remain — see TD-026 cluster note.)
- **TD-020 (P2) — cancelled_by_patient enum: CLOSED.** Migration j6cancelpatient2026 + agent + analytics. FIXLOG #90.
- **TD-023 (P2) — doctor calendar-id change resync: CLOSED.** FIXLOG #91.
- **TD-014 (P2) — Dockerfiles non-root: CLOSED.** FIXLOG #93.

## Still open (carry to post-launch / need Vinay)

- **TD-021 (P2)** — urgent walk-in bypass: PRODUCT DECISION needed (bypass full queue vs remove flag).
- **TD-022 (P3)** — cosmetic `if True:` de-indent in agent.py.
- **TD-024 (P3)** — solo-cap watchdog grace mid-confirm.
- **TD-026 (P3, mostly resolved 06-16 / FIXLOG #131)** — token capacity now frees cancelled/rescheduled seats by gating on the CONFIRMED-seat count, not the monotonic counter. Residual: daily_token_limit is advisory at assign (authoritative at confirm), so exact-simultaneous CONFIRMS can exceed it by a few (queue soft-cap, NOT a double-booking — numbers stay atomic+unique). Fully-atomic cap that also frees seats needs the 2-key design (monotonic number key + decrementable seats key); deferred until single-DID concurrency makes it matter.
- **G15 (LOW)** — CSP img-src/style-src tightening pending a frontend render check.
- **SEC-2026-07-11 residual (security audit LOWs / one MEDIUM, deferred for Vinay triage):**
  - **#8 (MED)** — during a Redis outage the rate limiter, IP blocklist, AND Turnstile all fail OPEN together, leaving the public auth surface unthrottled. Token-locking correctly stays fail-CLOSED. Fix: a small in-process (per-worker) fallback throttle on `/auth/*` so a Redis blip doesn't fully open brute-force. Not yet built — needs an in-memory limiter that doesn't reintroduce the #305 client leak.
  - **#12/#13 (LOW)** — JWT in localStorage (XSS-exfiltratable) + permissive CSP `img-src https:` / `style-src 'unsafe-inline'` don't contain token exfiltration. Fix: httpOnly cookie + CSRF, or tighten CSP to explicit origins (ties to G15).
  - **#15 (LOW)** — any single super_admin can mint another super_admin (`/admin/add-owner`) with no second-approval/step-up. Platform-takeover blast radius on one super_admin compromise.
  - **#16 (LOW)** — `max_call_duration_seconds=0` (unlimited) default + copy-only 500-min trial cap = call-duration / trial-minute cost-bleed. (Trial hard-cap now enforced per #308; per-call ceiling still open.)
  - **#18 (LOW)** — owner sets staff/doctor passwords directly (knows them permanently); no invite-link self-set flow.
  - **#10 (LOW)** — `google-service-account.json` private key sits unencrypted in the working tree (gitignored + excluded from image — verified — but it's under OneDrive sync). Move to `GOOGLE_SA_JSON_B64` env even in dev.
- **TD-027 (P2)** — broken alembic migration chain: `8559268c0c44` (phase45) is a from-scratch *rewrite* of the initial schema `ffcf1134aa8f` — both `create_table('organizations')` + the same full table set, so `alembic upgrade head` from base collides ("relation organizations already exists") and rolls back. Never caught because tests + local + prod startup build schema from models via `Base.metadata.create_all`, not migrations. Neon prod (2026-06-16) was provisioned via create_all + `alembic stamp head` (now at p12consent2026); future migrations apply cleanly from head. Fix when convenient: rewrite `8559` as ALTERs (audit_log add + FK ondelete=RESTRICT) and squash the early chain so a from-base upgrade works for fresh environments. Until then, new envs must bootstrap via create_all + stamp, NOT upgrade-from-base.
- **TD-028 (P3, bounty B16)** — two BillingCycle conventions coexist: webhook activation writes `cycle_start=today, cycle_end=today+30d` (`backend/routers/payments.py`) while scheduled plan changes use `next_cycle_start` (1st of next month). Latent — nothing meters against BillingCycle yet (metering is calendar-month over CallLog). Pick ONE convention before overage invoicing goes live.
- **TD-038 (P2, #342)** — invoice numbers are `VAC-YYYYMMDD-{payment-tail}` (unique + traceable, NOT statutory consecutive serials). GST rules require consecutive invoice serials per FY once we issue real tax invoices. When VACHANAM_GSTIN lands: add a DB sequence (per-FY) and store the number on BillingCycle. Also revisit CGST/SGST vs IGST split (currently one "GST @ 18%" line — needs place-of-supply once registered). TD-028 partially resolved by #340/#341: cycles are now anniversary-anchored end-to-end and overage meters against the cycle window; the leftover is only the legacy `next_cycle_start` fallback (unused in the main path).

## Paid down — 2026-07-12 (ledger cleanup pass, FIXLOG #344)

Verified-done rows closed above (they'd been paid for weeks without ledger updates):
TD-005/030/033 (emergency-keyword era, feature removed), TD-018/019 (FK indexes +
ondelete in phase45), TD-020/021 (voice overhaul superseded), TD-022 (audit PII
denylist live), TD-024 (static-page CSP superseded by PWA checkout), TD-026
(login-failure audit live), TD-027-retention (data_retention.py in prod), TD-029
(Shannon superseded by #312/#313 audits), TD-032 (conftest rewritten #324),
TD-014 (closed 06-13, row stale), TD-027-clone (voice cloning shipped).

Fixed TODAY (#344):
- **TD-037** — python-jose → PyJWT across backend + all tests; vulnerable `ecdsa`
  transitive dep gone; `--ignore-vuln` removed from security.yml. Suite green.
- **TD-025** — queue.py bare `except Exception` narrowed to
  `(SQLAlchemyError, OSError, RuntimeError)`.
- **SEC #8 (MED)** — Redis outage no longer leaves auth UNLIMITED: per-worker
  in-memory fallback window 429s past the limit (test proves 4th call throttled).
- **TD-028** — `scripts/dsar.py`: export/correct/delete/withdraw, branch-scoped
  (RULE 1), delete via the shared erasure path, audit-logged. 5 tests.
- **TD-036** — `scripts/check_vobiz_did_ready.py`: onboarding pre-flight for the
  three June-06 silent killers (KYC, empty provider, recycled DID).

Still open on purpose: TD-021-walkin (needs Vinay's product call), TD-022-ifTrue +
TD-024-watchdog (P3, churn>value), TD-023 (audit GRANT/REVOKE needs a second prod
DB role — Neon single-role today), TD-026/034/035 (Phase 9 onboarding), TD-031
(conditional), TD-027-alembic-chain (documented workaround), #10/#12/#13/#15/#16/#18
+ G15 (security backlog for a dedicated pass), TD-038 (gated on GSTIN).

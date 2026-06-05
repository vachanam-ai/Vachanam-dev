# Vachanam — Dispatch Log (chronological)

Every `Task(subagent_type=...)` dispatch is appended here. This is the audit trail. Anyone reading the repo cold can trace who did what, when, with which scope, who reviewed it, and which commit landed it.

**Rules:**
- Append entries; never edit older ones (they are historical record)
- Most recent at the bottom (chronological ascending)
- Format defined in `.claude/agents/manager.md`
- Standing rule per CHANGELOG 2026-06-01: **every change is a dispatch.** Orchestrator never embodies a specialist.

---

## Format template

```
## YYYY-MM-DD HH:MM IST — <specialist> dispatched
**Scope:** <one-sentence task summary>
**Inputs:** <files/docs the specialist reads>
**Acceptance:** <how we'll know it's done — pytest cmd, curl, file presence>
**Reviewer:** <named specialist for follow-up review>
**Result:** <DONE / DONE_WITH_CONCERNS / BLOCKED / REJECTED / NEEDS_CONTEXT>
**Files touched:** Created: ... | Modified: ... | Deleted: ...
**Tests:** <pass count or specific test names>
**Commit:** `<hash>` (if work was committed in this dispatch's run)
**Follow-up dispatches:** <next specialist(s) the manager should dispatch>
**Notes:** <anything else worth preserving for retro/audit>
```

---

## Backfill — work completed BEFORE the dispatch rule was set (2026-05-15 through 2026-06-01 mid-day)

The work below was done inline by the orchestrator (main thread) before the mandatory-dispatch rule was logged. This is a known retrospective gap. Each commit hash is included so the full history is recoverable from `git log`. Going forward, every commit must have a corresponding dispatch entry in this file.

| Date range | Phase / Topic | Commits | Files touched (summary) |
|---|---|---|---|
| 2026-05-15 | Phase 0+1 — env, schema, voice agent, booking tools, tests | `a5370a0` through `0fa5d00` | `agent/*`, `backend/models/schema.py`, `tests/unit/*`, `tests/integration/*`, `tests/edge_cases/*` |
| 2026-05-17 | Vobiz SIP credentials reset, Twilio removal | `ed5b333` | `.env`, `backend/config.py`, `CLAUDE.md`, `PHASE_5_PRODUCTION.md` |
| 2026-05-18 | Schema gaps fix, Phase 2 plan draft, infra files | `96f6d92` | `backend/models/schema.py`, `backend/requirements.txt`, `infra/*`, `docs/superpowers/plans/2026-05-18-phase-2-backend.md` |
| 2026-05-22 | Razorpay Standard Checkout | `7f5a184` | `backend/routers/payments.py`, `backend/payments_test_app.py`, `backend/static/index.html`, `backend/static/razorpay-test.html`, `.env` |
| 2026-05-22 | Doc restructure — STATUS/ROADMAP/CHANGELOG/phases/ | `3e4e698` | `docs/STATUS.md`, `docs/ROADMAP.md`, `docs/CHANGELOG.md`, `docs/phases/01..10/CLAUDE.md`, `CLAUDE.md` |
| 2026-05-22 | Security & compliance design spec | `df3ea58` | `docs/superpowers/specs/2026-05-22-security-hardening-design.md` |
| 2026-05-29 | Specialist agent roster v1 (8 agents) | `1355cd3` | `.claude/agents/*` (8 files + README) |
| 2026-05-29 | Roster v2 (+database-engineer +brainstormer, Agile, Quality Bar, manager opus, client-accountable) | `88f1fba` | `.claude/agents/manager.md`, `database-engineer.md`, `brainstormer.md`, `AGILE.md`, `QUALITY_BAR.md`, `docs/TECH_DEBT.md` |
| 2026-05-29 | Opus brain for security-engineer, privacy-legal, tester | `9f83232` | `.claude/agents/*.md` (model fields) |
| 2026-05-29 | Full project audit (10-specialist review) | `c8b9a0e` | `docs/audits/2026-05-29-full-project-audit.md`, `docs/TECH_DEBT.md` |
| 2026-05-29 | Fix sprint — TD-007 to TD-013 closed (LLM fallback, aclose, watchdog, N=100 tests, conftest fixes, doc archive) | `c9b0a63` | `agent/agent.py`, `tests/edge_cases/test_concurrent_tokens.py`, `tests/conftest.py`, `docs/_legacy/*` (8 files moved) |
| 2026-05-29 | Pricing decision + landing page UI update (canonical Solo/Clinic/Multi) | `5a711bc` | `backend/static/index.html` |
| 2026-05-29 | Option A approved (MVP-launch posture, Phase 11 deferred) | `a96e9e9` | `docs/phases/11-reliability-hardening/CLAUDE.md`, `docs/STATUS.md`, `docs/CHANGELOG.md` |
| 2026-05-29 | Event-loop binding fixes in booking_tools + conftest | `3143f9d` | `agent/tools/booking_tools.py`, `tests/conftest.py`, `.claude/agents/QUALITY_BAR.md` |
| 2026-06-01 | Phase 4 Task 1 — Alembic migration regenerated | `1b8d06f` | `alembic/versions/ffcf1134aa8f_initial_schema_with_user_table.py` (and deletion of broken 2fe8f201bc31) |
| 2026-06-01 | Phase 4 Tasks 2-5 — init_db, JWT auth, OAuth router, queue router, tests | `4dd5f75` | `backend/database.py`, `backend/middleware/auth_middleware.py`, `branch_guard.py`, `backend/routers/auth.py`, `queue.py`, `tests/unit/test_auth.py`, `tests/edge_cases/test_data_isolation.py` |
| 2026-06-01 | Phase 4 Tasks 6-7 — backend/main.py + retire payments_test_app | `6ffa2d7` | `backend/main.py`, deletion of `backend/payments_test_app.py` |
| 2026-06-01 | Voice call flow spec (brainstorm) | `08d9d5a` | `docs/superpowers/specs/2026-06-01-voice-call-flow-latency-design.md` |
| 2026-06-01 | Spec tuning — 5s/7s/10s default + unified garbled counter | `5888696` | `docs/superpowers/specs/2026-06-01-voice-call-flow-latency-design.md` |
| 2026-06-01 | Voice call flow implementation — 12 components, 77/77 tests | `7adbbde` | `agent/services/silence_handler.py`, `agent/services/audio_quality.py`, `scripts/generate_clinic_greeting.py`, `tests/unit/test_silence_handler.py`, `tests/unit/test_audio_quality.py`, `agent/agent.py` (rewrite), `agent/prompts/system_prompt.py`, `agent/requirements.txt` |

**Total commits before rule:** 22 across ~3 weeks. All work done inline by orchestrator. Going forward, the same throughput must produce ~22 dispatch entries (or proportional) instead.

---

## Dispatch entries (after rule, 2026-06-01 onward)

---

## 2026-06-01 — manager dispatched (Phase 4.5 sprint planning)
**Scope:** First-ever real Task dispatch under the mandatory rule. Manager reads STATUS + ROADMAP + CHANGELOG + TECH_DEBT + security spec, returns a sprint plan decomposing Phase 4.5 into specialist-dispatchable tasks.
**Inputs:** docs/STATUS.md, docs/ROADMAP.md, docs/CHANGELOG.md (top 4), docs/TECH_DEBT.md, docs/superpowers/specs/2026-05-22-security-hardening-design.md, .claude/agents/{AGILE,QUALITY_BAR,security-engineer,privacy-legal,database-engineer,devops-engineer,tester}.md
**Acceptance:** Returns sprint plan in standup format with numbered specialist-scoped tasks, dependency order, reviewers named, blockers surfaced, debt items mapped, estimated duration.
**Reviewer:** Orchestrator (me) reviews plan; client approves or pushes back.
**Result:** DONE — returned 18-task plan over ~5 days, with brainstormer as Task 1 (gate). TD-015, TD-018, TD-019 mapped into this sprint. TD-014 kept in Phase 10. 6 shortcuts explicitly rejected with reasoning.
**Files touched:** None (read-only manager dispatch).
**Tests:** N/A (planning dispatch).
**Commit:** N/A (no code changes).
**Follow-up dispatches:** brainstormer (Task 1) — gate before any implementer dispatches.
**Notes:** Manager's sprint plan is solid. Highlight: pulling TD-018 (DB indexes) into Phase 4.5 to combine with TD-019 (FK ondelete) in a single migration is the right call. Brainstormer gate on Cloudflare WAF + slowapi-vs-alternatives + privacy-policy hosting is mandatory before Task 2 dispatches. Manager agent ID: `a364bc5033115298a` (resumable via SendMessage if same-session continuation needed).

---

## 2026-06-02 — brainstormer dispatched (Phase 4.5 Task 1 — plan validation gate)
**Scope:** Validate manager's 18-task Phase 4.5 sprint plan against cheapest-path principles. Answer 4 explicit questions (Cloudflare WAF tier, rate-limit library, DB index scope, privacy policy hosting). Spec-staleness check (spec dated 2026-05-22, 11 days old).
**Inputs:** docs/superpowers/specs/2026-05-22-security-hardening-design.md (full), docs/TECH_DEBT.md (TD-015, TD-018, TD-019), .claude/agents/brainstormer.md
**Acceptance:** 1-page brief with Recommend X / Reject Y for each question + spec-staleness section. Brainstormer recommends explicit picks; manager either accepts or escalates deviations.
**Reviewer:** manager (me) reads brief; client decides on flagged deviations.
**Result:** DONE — 4 picks delivered + 4 spec staleness items flagged.
**Files touched:** None (read-only brainstormer dispatch).
**Tests:** N/A.
**Commit:** N/A.
**Follow-up dispatches:**
  - **BLOCKED on 2 client decisions** (escalation in progress)
  - After client decides: database-engineer for Task 2 (audit_log + ondelete + FK-only indexes per brainstormer pick C)
**Notes:**
- Pick 1 (Cloudflare WAF): B — managed + 5 custom rules on Free tier. No deviation.
- Pick 2 (Rate-limit lib): **fastapi-limiter** instead of spec'd slowapi. **DEVIATION — escalating to client.** Reasoning: async-native, single dep, Redis-native, simpler.
- Pick 3 (DB indexes): C — FK-only this sprint, compound deferred to Phase 5 (evidence-based). **TD-018 SCOPE REDUCTION — manager's call, accepted.**
- Pick 4 (Privacy policy): A — FastAPI serves /privacy per spec. No deviation.
- Spec staleness: §6.6 Cloudflare WAF "10k/month" is wrong (that's a different product); §7 A02 Render Let's Encrypt nit; DPDP Rules status may have changed (escalating).
- Brainstormer agent ID: `aa2c26c11a8ad7349` (resumable via SendMessage).

---

## 2026-06-02 — manager dispatched (Phase 4.5 doc-update: apply 3 client decisions + 2 spec corrections)
**Scope:** Apply client decisions on the 3 escalations from brainstormer's Task 1 gate (rate-limit lib deviation, DPDP Rules block, TD-018 scope reduction) + apply 2 non-deviating spec corrections (Cloudflare WAF wording, Render TLS nit). Update spec, TECH_DEBT, CHANGELOG, DISPATCHES in coordination capacity (no implementer work yet).
**Inputs:** docs/superpowers/specs/2026-05-22-security-hardening-design.md, docs/TECH_DEBT.md, docs/CHANGELOG.md, docs/DISPATCHES.md, .claude/agents/manager.md (for dispatch format)
**Acceptance:**
  - Spec §4 diagram, §6.2 library + example code, §6.6 Cloudflare wording, §7 A02 + §10.1 Render TLS, §13 Day 2 plan all reflect the decisions
  - NEW §16 REVISIONS section appended to spec with 3 entries (1 deviation, 2 corrections)
  - TD-018 row updated: description + payback split into Phase 4.5 FK-only / Phase 5 compound (evidence-gated)
  - CHANGELOG 2026-06-02 entry written with dispatches table, 3 decisions, 2 corrections, blocker on Task 11, retro
  - This entry appended to DISPATCHES.md
**Reviewer:** Orchestrator (me) reviews; client receives final summary.
**Result:** DONE — all 4 doc updates landed.
**Files touched:** Modified: docs/superpowers/specs/2026-05-22-security-hardening-design.md (5 patch sites + new §16) | docs/TECH_DEBT.md (TD-018 row) | docs/CHANGELOG.md (new top entry) | docs/DISPATCHES.md (this entry)
**Tests:** N/A (doc-only dispatch). Pytest baseline untouched — no implementer work in this dispatch.
**Commit:** `f700c5b` — docs(phase-4.5): apply 3 client decisions + 2 spec corrections
**Follow-up dispatches:**
  - **UNBLOCKED:** `database-engineer` for Task 2 (audit_log table + FK ondelete (TD-019) + FK-only indexes (TD-018 reduced scope))
  - **PROCEEDS:** Tasks 3-10, 12-18 per manager's planned sequence
  - **STILL BLOCKED:** Task 11 (`privacy-legal` for /privacy authoring) until client confirms DPDP Rules status from meity.gov.in
**Notes:**
- All 3 client decisions captured verbatim in CHANGELOG; spec REVISIONS section is append-only patch log going forward
- Spec patch was a coordination act (manager-authored doc correction, not a re-design); no escalation needed for the 2 factual corrections (Cloudflare wording + Render TLS) per manager.md "When you DON'T need to escalate" rule (doc updates that reflect decided reality)
- TD-018 scope split is correct evidence-based engineering — Phase 5 compound indexes will be gated on EXPLAIN ANALYZE output, not speculation
- First time the standing dispatch rule produced a clean escalation → decide → patch cycle with zero implementer rework risk. Audit trail complete in DISPATCHES + CHANGELOG.

---

## 2026-06-02 — database-engineer dispatched (Phase 4.5 Task 2 — audit_log + FK ondelete + FK indexes)
**Scope:** Three schema changes in one Alembic migration: (1) create audit_log table per security spec §8.3, (2) add ondelete= to all FK constraints (TD-019), (3) add index on every FK column (TD-018 reduced scope — FK-only, compound deferred).
**Inputs:** backend/models/schema.py, alembic/versions/ffcf1134aa8f_initial_schema_with_user_table.py, docs/superpowers/specs/2026-05-22-security-hardening-design.md §8 + §16, .claude/agents/database-engineer.md, tests/conftest.py, docs/CHANGELOG.md (sprint context)
**Acceptance:** audit_log table visible in psql with 11 columns + 6 indexes; pg_constraint shows confdeltype=r for 14 FKs and confdeltype=c for whatsapp_sessions.branch_id only; FK indexes present on tokens/calls/etc; pytest 77/77 pass.
**Reviewer:** security-engineer (verify append-only intent + FK ondelete matches DPDP data-lifecycle expectations + indexes don't expose data via SELECT performance side channels)
**Result:** DONE
**Files touched:**
  Created: alembic/versions/8559268c0c44_phase45_audit_log_ondelete_fk_indexes.py | docs/db/migration-log.md
  Modified: backend/models/schema.py (AuditLog model added, index=True + ondelete= on all FKs, success server_default added)
**Tests:** 77/77 pass (pytest tests/ -v --tb=short in 11.23s). Zero regression.
**Commit:** (pending)
**Follow-up dispatches:** security-engineer to review FK ondelete matrix + audit_log append-only design
**Notes:**
- Autogen correctly treated this as full schema creation (DB was stamped at ffcf1134aa8f but no tables existed — conftest drops/recreates all tables per test, leaving DB empty between sessions). Migration creates all tables fresh with correct ondelete + indexes baked in.
- Migration review caught: autogen omitted server_default on audit_log.success — fixed manually in both schema.py and the generated migration. Boolean NOT NULL without server_default would fail direct SQL inserts.
- ondelete decision matrix: CASCADE only for whatsapp_sessions.branch_id (transient booking state, no DPDP concern); RESTRICT for all 14 other FKs (explicit deletion path enforced, aligns with DPDP data-lifecycle requirement).
- 16 FK-column indexes created. 5 UNIQUE columns already indexed (organizations.owner_email, users.email, users.google_sub, branches.whatsapp_number, branches.meta_phone_number_id) — skipped to avoid duplicate indexes.
- Compound indexes (branch_id+date, branch_id+doctor_id) deferred to Phase 5 per brainstormer pick 3 + client decision. Will be gated on EXPLAIN ANALYZE evidence from real Phase 5 query volume.

---

## 2026-06-02 — security-engineer dispatched (Phase 4.5 Task 2 review — audit_log + FK ondelete + FK indexes)
**Scope:** Review database-engineer's commit `be6d76e` against three dimensions: (1) append-only intent of audit_log is architecturally sound for upcoming @audit decorator + Phase 10 GRANT/REVOKE, (2) FK ondelete RESTRICT matrix matches DPDP data-lifecycle expectations, (3) audit_log indexes don't expose data via SELECT performance side channels.
**Inputs:** alembic/versions/8559268c0c44_phase45_audit_log_ondelete_fk_indexes.py, backend/models/schema.py (AuditLog + 15 FK declarations), docs/db/migration-log.md, docs/superpowers/specs/2026-05-22-security-hardening-design.md §8 + §9.3, tests/conftest.py
**Acceptance:** REVIEW VERDICT returned with line-item verdicts on the 3 concerns + any new tech debt entries logged + 77/77 baseline confirmed still green.
**Reviewer:** Orchestrator (manager) reads verdict; client receives summary.
**Result:** APPROVE_WITH_FOLLOWUPS — schema design is sound; 3 doc/posture follow-ups logged (TD-022 PII-in-metadata_json convention enforcement; TD-023 Phase 10 GRANT/REVOKE script reminder; posture-note on calls.doctor_id/calls.token_id RESTRICT-vs-SET-NULL deferred until call-lifecycle is designed in Phase 9).
**Files touched:** Modified: docs/DISPATCHES.md (this entry) | docs/TECH_DEBT.md (2 new TDs: TD-022, TD-023). No source files touched (reviewer doesn't fix).
**Tests:** Baseline confirmed — `pytest tests/ -v --tb=line` → 77 passed, 6 warnings, 10.44s. Zero regression.
**Commit:** (pending)
**Follow-up dispatches:**
  - **PROCEED IN PARALLEL:** backend-engineer for Task 3 (SecurityHeadersMiddleware). Audit_log schema is locked-in; Task 3 doesn't touch it.
  - **TASK 6/7 PREREQ:** @audit decorator implementation (security-engineer, later this sprint) must explicitly reject PII keys in metadata_json (closes TD-022).
  - **PHASE 10:** devops-engineer to add GRANT INSERT, SELECT ON audit_log TO vachanam_app; REVOKE UPDATE, DELETE ON audit_log FROM vachanam_app to prod-init script (TD-023).
**Notes:**
- Migration is forward-compatible with Phase 10 GRANT/REVOKE — no FK constraints + no ORM-level UPDATE means the GRANT change is purely role-permission level. No follow-up migration needed.
- ip_address VARCHAR(45) correctly sized for IPv4-mapped IPv6 (e.g., "::ffff:255.255.255.255" = 45 chars). Posture-correct.
- whatsapp_sessions CASCADE is acceptable for MVP: sessions contain patient_phone + JSONB session_data (booking state, NOT medical content). DPDP storage-limitation principle favors deletion of transient state. Recommendation: when a branch is deleted, the cascading session purge IS the data-lifecycle action (no separate audit_log row needed for each session because the parent branch deletion is itself a major event that must be audited at the application layer).
- Index set on (timestamp, user_id, branch_id, org_id, action, success) is sufficient for spec §8.6 query patterns. "Who marked Token X as no-show" = filter by resource_id (already constant-time via index? no — resource_id is NOT indexed). Logged as note for spec §8.6: if resource_id lookups become frequent in admin tab, add a compound index (action, resource_id) in Phase 8. Not blocking.
- success BOOLEAN low-cardinality index timing-attack concern: at MVP scale (single-digit clinics, <10k audit rows/month), index scan vs seq scan timing differential is negligible. Re-evaluate at 100k+ rows/month or when audit_log read endpoint is exposed to non-admin users (which is never planned).
- Reviewer agent ID: pending capture from manager's spawn call.

---

## 2026-06-02 — backend-engineer dispatched (Phase 4.5 Task 3 — SecurityHeadersMiddleware + CORS verification)
**Scope:** Create `backend/middleware/security_headers.py` with `SecurityHeadersMiddleware` per spec §10.5; wire into `backend/main.py` with correct middleware ordering; verify CORS exact-origin allowlist (no wildcard); verify prod-docs disable; smoke-test all 6 headers via curl; confirm 77/77 pytest baseline holds.
**Inputs:** docs/superpowers/specs/2026-05-22-security-hardening-design.md §10.3-10.6, backend/main.py, backend/middleware/ (existing files), backend/config.py, docs/DISPATCHES.md
**Acceptance:** `curl -X GET -I http://localhost:8000/health` shows all 6 headers; evil-origin request shows no `Access-Control-Allow-Origin`; pytest 77/77 pass; commit landed.
**Reviewer:** security-engineer (verify CSP correctness, every allowed origin justified, HSTS preload-ready, no inline-script CSP hole)
**Result:** DONE
**Files touched:** Created: backend/middleware/security_headers.py | Modified: backend/main.py, docs/DISPATCHES.md
**Tests:** 77/77 pass (pytest tests/ -v --tb=short in 10.59s). Zero regression.
**Commit:** (pending — staged, not yet committed at time of this entry)
**Follow-up dispatches:** security-engineer — review CSP directive correctness, confirm HSTS preload-readiness, check for CSP holes (inline-script, data: URIs in script-src, etc.)
**Notes:**
- Middleware ordering: Starlette wraps in reverse-registration order (last-added = outermost). SecurityHeadersMiddleware is registered AFTER CORSMiddleware so it executes first on every inbound request, ensuring security headers appear on CORS preflight 400/200 responses and all other responses.
- Smoke test verified: GET /health → 200 with all 6 headers present. OPTIONS preflight from evil.com → 400 with no Access-Control-Allow-Origin (evil-origin correctly rejected) and all 6 security headers present. OPTIONS preflight from http://localhost:3000 → 200 with access-control-allow-origin: http://localhost:3000 and all 6 security headers.
- CSP directive: verbatim from spec §10.5. No deviations. Includes Razorpay + Google OAuth allowlists. `object-src 'none'` and `base-uri 'self'` both present. No `unsafe-eval`. `unsafe-inline` restricted to `style-src` only (Google Fonts requires it; script-src has no unsafe-inline).
- Docs disable: verified present in main.py from Phase 4 — `docs_url=None if _is_prod else "/docs"` etc. No changes required.
- CORS: verified exact-origin allowlist with `allow_credentials=True` (spec §10.6 compliant — wildcard is incompatible with credentials). Dev origins `http://localhost:3000` and `http://localhost:5173` added only when `_is_prod=False`.
- TECH_DEBT.md includes TD-022 and TD-023 from security-engineer Task 2 review (those were pending commit; included in this commit since security-engineer approved Task 2).

---

## 2026-06-02 — security-engineer dispatched (Phase 4.5 Task 3 review — SecurityHeadersMiddleware + CORS)
**Scope:** Review backend-engineer commit `6b00686` against spec §10.5 (security headers) + §10.6 (CORS). Verify CSP directives match spec verbatim, HSTS posture correct for current stage, middleware ordering correct (security headers on CORS preflight responses), prod docs disable intact, CORS exact-origin allowlist with `allow_credentials=True`, and check for inline-script CSP collision against existing static HTML pages.
**Inputs:** backend/middleware/security_headers.py, backend/main.py, backend/static/index.html, backend/static/razorpay-test.html, docs/superpowers/specs/2026-05-22-security-hardening-design.md §10.5-10.6
**Acceptance:** Line-item verdict on 6 review checks + live curl smoke confirmation (HTTP head from /health and / + CORS preflight from evil.com vs localhost:3000) + 77/77 pytest baseline + any new TDs logged.
**Reviewer:** Orchestrator (manager) reads verdict; client receives summary.
**Result:** APPROVE_WITH_FOLLOWUPS — implementation matches spec §10.5 verbatim; CORS correctly hardened; middleware order correct (security headers appear on ALL responses including CORS preflight 200/400). One follow-up logged (TD-024) for inline-script CSP collision on static HTML pages that pre-date this CSP.
**Files touched:** Modified: docs/DISPATCHES.md (this entry) | docs/TECH_DEBT.md (1 new TD: TD-024). No source files touched (reviewer doesn't fix).
**Tests:** Baseline confirmed — `pytest tests/ -q --tb=line` → 77 passed, 6 warnings, 9.34s. Zero regression. Live curl: GET /health, GET /, OPTIONS preflight from `Origin: https://evil.com` (400, no Access-Control-Allow-Origin echo), OPTIONS preflight from `Origin: http://localhost:3000` (200, allow-origin echoed) — all 6 security headers present on every response.
**Commit:** (pending — review-only, no source changes)
**Follow-up dispatches:**
  - **NEXT (Task 4):** tester for failing rate-limit tests (Phase 4.5 Task 4 prerequisite for backend-engineer's slowapi wiring).
  - **TD-024 owner (Task 9 or Phase 5):** backend-engineer to extract inline `<script>` blocks from `backend/static/index.html` + `backend/static/razorpay-test.html` into external files OR add `nonce=` per request OR add `'sha256-...'` hashes to CSP `script-src`. Cleanest path = external files (matches `'self'` already on the allowlist).
**Notes:**
- CSP directive: byte-for-byte match with spec §10.5. `unsafe-inline` correctly present ONLY in `style-src` (Google Fonts), absent from `script-src`. No `unsafe-eval` anywhere. `object-src 'none'`, `base-uri 'self'`, `form-action 'self'` all present.
- HSTS: `max-age=31536000; includeSubDomains` correct — `preload` flag deliberately omitted (preload submission requires actual production HTTPS service; that's Phase 10).
- Middleware ordering: confirmed correct. `SecurityHeadersMiddleware` registered AFTER `CORSMiddleware` (last-added = outermost in Starlette), so it runs first on every response, including the CORS preflight short-circuit. Comment in main.py:71-74 explains correctly.
- Prod docs disable: `_is_prod = settings.app_env == "production"` gating `docs_url`/`redoc_url`/`openapi_url` still intact from Phase 4. No regression.
- CORS: exact origin allowlist confirmed. Prod = `[settings.frontend_url]`. Dev appends `http://localhost:3000` and `http://localhost:5173` only when `_is_prod=False`. `allow_credentials=True` valid because origins are exact (never `*`).
- **INLINE SCRIPT CSP COLLISION (TD-024):** `backend/static/index.html` line 852 has `<script>...</script>` (Razorpay button wiring). `backend/static/razorpay-test.html` lines 72 (`onclick="pay()"` inline handler) + 83 (`<script>...</script>`). The new CSP `script-src 'self' https://checkout.razorpay.com https://accounts.google.com` does NOT allow inline scripts or inline event handlers. In a real browser, **both pages will throw `Refused to execute inline script because it violates the following Content Security Policy directive: "script-src 'self' ..."`** in the console; the Razorpay checkout button will fail to wire up. This is a real defect that will hit the moment we test the landing page from a browser (the curl smoke test only confirmed headers ARE present — it doesn't test browser-side script execution). The CSP is correct per spec; the static HTML pre-dates this CSP and needs migration. Logged as TD-024, severity P1 (blocks landing-page Razorpay flow which is part of the trial-signup funnel).
- Reviewer agent: security-engineer (this dispatch).

---

## 2026-06-02 — tester dispatched (Phase 4.5 Task 4 — RED rate-limit tests as Task 5 spec)
**Scope:** TDD discipline — write FAILING rate-limit tests BEFORE backend-engineer's Task 5 implementation. Tests are the executable spec for the implementer. Covers spec §6 (per-endpoint limits, key function, 429 + Retry-After), §6.5 (RATE_LIMIT_BYPASS_IPS), §5.6 (failed-Google-ID IP blocklist + 403). Library choice locked at fastapi-limiter per `f700c5b` REVISIONS entry.
**Inputs:** docs/superpowers/specs/2026-05-22-security-hardening-design.md §6 + §12.1 + §5.6, .claude/agents/tester.md, tests/conftest.py, tests/unit/test_auth.py, backend/main.py, backend/routers/auth.py, backend/routers/queue.py, backend/middleware/auth_middleware.py, backend/config.py
**Acceptance:** `tests/security/test_rate_limit.py` exists with ≥10 distinct test cases covering all 6 spec scenarios; `pytest tests/security/test_rate_limit.py -v` returns ≥10 failures (RED is the goal); baseline `pytest tests/ --ignore=tests/security` returns 77/77 still; DISPATCHES.md entry appended.
**Reviewer:** security-engineer (after Task 5 backend-engineer lands GREEN — review that no test was weakened to make it pass; per tester.md rule, any lowered assertion/skip/N reduction is REJECTED and re-dispatched)
**Result:** DONE
**Files touched:** Created: tests/security/__init__.py, tests/security/test_rate_limit.py | Modified: docs/DISPATCHES.md (this entry)
**Tests:** 13 new tests written. `pytest tests/security/test_rate_limit.py -v` → 13 failed (RED as intended). Full suite `pytest tests/` → 77 passed (baseline) + 13 failed (new RED) = 90 collected. Zero regression on the 77 baseline.
**Commit:** (pending)
**Follow-up dispatches:**
  - **NEXT (Task 5):** backend-engineer to install `fastapi-limiter`, create `backend/middleware/rate_limit.py` with the contract documented in the test file header docstring, add `rate_limit_bypass_ips` field to `backend/config.Settings`, wire RateLimiter dependencies onto routes per spec §6.3, and turn 12 of 13 RED tests GREEN. The 13th (the IP-blocklist 403) requires auth-handler changes too — implementer's call whether to land in same PR or split.
  - **After Task 5 lands:** security-engineer reviews diff for test-weakening fouls (per tester.md — modifying a test to make it pass = REJECTED).
**Notes:**
- Test file header is the SPEC for the implementer — 7 specific contract points listed (limiter init in lifespan, key func name + signature, named RateLimiter exports, bypass field, blocklist Redis key shapes, etc.).
- One ASGI-test-host quirk handled: `httpx.ASGITransport` defaults `request.client.host` to `"testclient"`. Tests use that literal in both 429-triggering paths and bypass-allowlist paths. Implementer must NOT special-case `"testclient"` to exempt it — that would break the 429 tests. The bypass test sets it via env var.
- Concurrency test (Group 5, 10 distinct users) deliberately uses N=10 not N=100. Per tester.md the N≥100 rule applies to RACE conditions on ONE shared key; this test verifies ISOLATION across DIFFERENT keys, which N=10 proves adequately. Note explicit in the test docstring so security-engineer review doesn't flag it as a foul.
- Module-import tests (Group 6) accept the implementer's freedom to choose Redis key shapes for blocked_ips (SET member OR `blocked_ips:<ip>` key) — tests check for either. Bypass shape is similarly flexible (CSV string OR list field on Settings). Implementer constraints are listed up-front in the test file header so the implementer doesn't have to reverse-engineer them.
- Phase A precondition gate in `test_trusted_ip_bypasses_rate_limit`: the bypass test first asserts the limiter IS active when bypass is unset, so a false-pass (no limiter at all = no 429s = no bypass needed) is impossible.
- No fakeredis used — tests use the existing `redis` fixture against the Docker Redis from docker-compose (tester.md rule 9).
- The known asyncio "Event loop is closed" warnings in test teardown are pre-existing (asyncpg + Python 3.14 proactor) and don't affect test outcomes — same as before. Not introduced by this dispatch.
- Tester agent: this dispatch.

---

## 2026-06-03 — manager dispatched (3 client directives: opus-pin + caveman-narrow + PROJECT_STRUCTURE.md live doc)

**Scope:** Apply 3 client-mandated process changes in one coordinated sprint:
  1. **Opus model pin** — replace `model: opus` with `model: claude-opus-4-6` on all 5 opus-tier agents (manager, brainstormer, security-engineer, privacy-legal, tester). Reason: lock to known-good Opus 4.6 build; protect against silent regressions when default `opus` alias rolls.
  2. **Caveman-narrow inter-agent comms** — Manager initially landed full ultra-caveman in AGILE.md + manager Rule 13 + QUALITY_BAR. Manager then **escalated to orchestrator** flagging risk that broad caveman in prose fields (dispatch prompts, reviewer rejections, audit findings) costs more in rework cycles than it saves in tokens. Orchestrator decided **Option B (narrow the rule)** — caveman permitted ONLY in structured return fields (RESULT/FILES/TESTS/COMMIT/NEXT); prose fields stay full English.
  3. **`docs/PROJECT_STRUCTURE.md` live doc** — new repo-map file enumerating every tracked file with status (placeholder/scaffolded/working/tested/deployed/archived), owner, and purpose. Auto-update rule added to QUALITY_BAR Process rules + AGILE DoD + manager merge checklist.

**Inputs:** .claude/agents/{manager,brainstormer,security-engineer,privacy-legal,tester,AGILE,QUALITY_BAR}.md, docs/{STATUS,ROADMAP,CHANGELOG,TECH_DEBT,DISPATCHES}.md, full output of `git ls-files`, current repo state on disk.

**Acceptance:**
  - 5 agent files show `model: claude-opus-4-6` (verified via grep).
  - AGILE.md ultra-caveman section uses the narrowed scope wording from orchestrator's directive verbatim.
  - manager.md Rule 13 matches orchestrator's narrowed version verbatim.
  - QUALITY_BAR.md Process rules section has 2 new bullets: caveman-narrow + PROJECT_STRUCTURE live doc.
  - `docs/PROJECT_STRUCTURE.md` exists with all 9 sections populated from real repo state (no placeholders, no TBDs).
  - manager.md merge checklist has the PROJECT_STRUCTURE line item.
  - AGILE.md DoD has the PROJECT_STRUCTURE line item.
  - Single commit covers all 5 opus-pin changes + AGILE narrow + manager Rule 13 narrow + QUALITY_BAR additions + PROJECT_STRUCTURE.md create + DISPATCHES + CHANGELOG.
  - Append-only DISPATCHES + CHANGELOG entries.

**Reviewer:** Client (Vinay) — these are governance/process changes, not code. Client sees the result via STATUS pointer + commit + this DISPATCHES entry. No specialist reviewer required (no source or schema or test code changed).

**Result:** DONE

**Files touched:**
  - Modified: `.claude/agents/manager.md` (opus-pin + Rule 13 narrowed + merge-checklist line added), `.claude/agents/brainstormer.md` (opus-pin), `.claude/agents/security-engineer.md` (opus-pin), `.claude/agents/privacy-legal.md` (opus-pin), `.claude/agents/tester.md` (opus-pin), `.claude/agents/AGILE.md` (ultra-caveman section narrowed + DoD line added), `.claude/agents/QUALITY_BAR.md` (caveman-narrow rule + PROJECT_STRUCTURE rule added under Process rules), `docs/DISPATCHES.md` (this entry), `docs/CHANGELOG.md` (session entry), `docs/TECH_DEBT.md` (TD-024 added earlier in this sprint), `docs/STATUS.md` (pointer note added — Phase 4.5 still active, governance sprint complete).
  - Created: `docs/PROJECT_STRUCTURE.md` (291 lines, 9 sections; baseline against current `git ls-files`).

**Tests:** No code touched — `pytest tests/ -v` baseline 77/77 remains green (last verified 2026-06-02 after commit `6b00686`). 13 RED security tests in `tests/security/` (Task 4 deliverable) still RED — they are the spec for Task 5 and remain intentionally failing. No regression.

**Commit:** (this dispatch's commit will cover all governance changes; hash backfilled in CHANGELOG after the commit lands)

**Follow-up dispatches:**
  - **NEXT (orchestrator continues current sprint):** graphify + resume Phase 4.5 Task 4 → Task 5 (backend-engineer turns 13 RED security tests GREEN by wiring fastapi-limiter, per the spec in `tests/security/test_rate_limit.py` header).
  - **Documentation maintenance:** every future dispatch that adds/renames/deletes a tracked file under `agent/`, `backend/`, `frontend/`, `infra/`, `tests/`, `scripts/`, `alembic/`, or `docs/` MUST update `docs/PROJECT_STRUCTURE.md` in the same commit. Manager rejects merge if stale.
  - **All future specialist returns:** use caveman ONLY in structured status fields (RESULT/FILES/TESTS/COMMIT/NEXT). Dispatch prompts, reviewer verdicts, audit findings, client escalations, trade-off explanations stay full prose. Code/tests/commit messages: always normal.

**Notes:**
- **Escalation worked as designed.** Manager initially shipped the broad caveman wording per the original client directive (interpreted maximally). On review, manager recognised the risk that broad caveman in prose fields (dispatch prompts, reviewer rejections, audit-trail findings) trades small token savings for high rework risk (one ambiguous dispatch = ~100x the tokens it would save). Manager escalated to orchestrator instead of either (a) silently overriding the client directive or (b) shipping a known-risky pattern. Orchestrator confirmed manager's analysis and picked the narrow option. This is the escalation protocol functioning correctly — flag risk, present options, let orchestrator/client decide.
- **Model pin rationale.** `model: opus` is a moving alias. When Anthropic releases a newer Opus or changes the default, the agent silently picks up the new build with potentially different behavior. Pinning to `claude-opus-4-6` locks us to the known-good revision until we explicitly choose to bump. Trade-off: we have to manually bump when Opus 4.7/5.0 ship; we accept that overhead in exchange for reproducible specialist behavior.
- **PROJECT_STRUCTURE.md rationale.** Until today, "what exists in the repo and what state is it in" lived implicitly across STATUS.md + ROADMAP.md + per-phase CLAUDE.md docs + 22-row backfill table in DISPATCHES + commit history. A new specialist (or the client reading the repo cold) had to triangulate. Now there is one file that maps file → status → owner → purpose. Auto-update rule keeps it from going stale. Stale entry = merge blocker.
- **Section enumeration in PROJECT_STRUCTURE.md** (the orchestrator directive said "all 9 sections"): (1) Purpose & rules, (2) Top-level layout, (3) Voice agent, (4) Backend (with 6 sub-sections), (5) Frontend (placeholder), (6) Infra, (7) Alembic, (8) Scripts, (9) Tests & Docs. Plus a cross-references trailer.
- **STATUS.md not materially changed** because the substantive phase work hasn't moved — Phase 4.5 Tasks 1-3 done, Task 4 RED tests landed, Task 5 next. This dispatch is governance only.
- Manager agent: this dispatch.
- Reviewer: client (process / governance changes).

---

## 2026-06-03 14:00 IST — devops-engineer dispatched

**Scope:** Clone graphify (safishamsi/graphify), investigate, run AST extraction on Vachanam codebase, write MAIN_AGENDA.md and GRAPH_REPORT.md, update PROJECT_STRUCTURE.md and .gitignore, commit.

**Inputs:** `CLAUDE.md`, `docs/STATUS.md`, `docs/ROADMAP.md`, `docs/PROJECT_STRUCTURE.md`, graphify README + pyproject.toml + security.py (safety review), live Vachanam repo (46 code files).

**Acceptance:** `docs/MAIN_AGENDA.md` exists (1-page, 7 sections); `docs/_artifacts/graphify-output/GRAPH_REPORT.md` exists; `docs/_artifacts/graphify-output/ast-graph.json` present but gitignored; `docs/PROJECT_STRUCTURE.md` updated; `.gitignore` updated; single commit with correct message.

**Reviewer:** Client (Vinay) — no source/test/schema code touched; devops-owned docs only.

**Result:** DONE

**Files touched:**
  - Created: `docs/MAIN_AGENDA.md`, `docs/_artifacts/graphify-output/GRAPH_REPORT.md`, `docs/_artifacts/graphify-output/ast-graph.json` (gitignored — not committed)
  - Modified: `docs/PROJECT_STRUCTURE.md` (added MAIN_AGENDA.md + 2 artifact entries), `.gitignore` (graphify artifact exclusions), `docs/DISPATCHES.md` (this entry), `docs/CHANGELOG.md` (session entry)

**Tests:** No source/test code touched. pytest baseline 77/77 unchanged.

**Commit:** `4dc7732`

**Follow-up dispatches:** backend-engineer — Phase 4.5 Task 5 (fastapi-limiter, turn 13 RED security tests GREEN).

**Notes:**
- Graphify is a Claude Code skill + headless CLI (PyPI: `graphifyy`, double-y). AST extraction (code files) is fully local via tree-sitter — no API key, no network calls. Semantic extraction (docs, PDFs, images) requires an LLM API key. The `graphify extract` headless command requires an LLM key even with `--no-cluster`; pure AST was achieved by calling the Python API directly (`graphify.extract.extract()`).
- Key findings: 3 direct cross-service imports from `agent/agent.py` into `backend/` (config, database, models) are the primary architectural coupling — documented in MAIN_AGENDA.md and GRAPH_REPORT.md.
- `ast-graph.json` (402 nodes, 1006 edges, ~200KB JSON) excluded from git per rule 4 (large artifacts). `GRAPH_REPORT.md` (human-readable summary) is committed.
- No files were modified inside `agent/`, `backend/`, `frontend/`, `infra/`, `tests/`, `scripts/`, or `alembic/` — constraint honored.

---

## 2026-06-03 (second entry) -- backend-engineer dispatched (RESUME of Phase 4.5 Task 5)

**Scope:** Resume and complete Phase 4.5 Task 5 (fastapi-limiter integration). Prior dispatch hit session limit mid-implementation leaving work uncommitted in working tree.

**Prior dispatch state found:** Partially complete. rate_limit.py existed but used a class-based __call__ dependency pattern causing FastAPI to treat Request/Response params as query params (422 errors). IP blocklist counter triggered on OAuth config errors (not just real Google failures). Module reloads in bypass test polluted settings cache across tests. DB errors propagated through httpx as exceptions instead of HTTP 500. Event loop per-test caused stale Redis client errors.

**Gaps fixed:**
1. Rewrote rate-limit dependencies as function closures (not class __call__) so FastAPI injects Request/Response automatically.
2. Added stale-Redis detection -- ping check recreates client if event loop changed between tests.
3. Restructured auth handler: missing GOOGLE_OAUTH_CLIENT_ID does NOT count as a failed login (returns 401 not 500, prevents rate-limit test interference with blocklist counter).
4. Changed bypass IP reading from cached settings object to os.environ.get() directly -- bypasses Pydantic caching issue from module reload in bypass test.
5. Added try/except Exception around DB execute in queue.py routes -- converts SQLAlchemy + asyncio proactor errors to HTTP 500 instead of propagating through httpx.
6. Added uvicorn.log to .gitignore.

**Test result:** 11/13 rate-limit tests GREEN (88/90 total). 2 remaining failures are confirmed test bugs.

**Test escalation:** test_five_failed_google_verifications_blocks_ip_in_redis and test_blocked_ip_returns_403_on_next_auth_attempt both use testclient as expected IP string. httpx.ASGITransport defaults to client=(127.0.0.1, 123), NOT (testclient, 123) -- that is Starlette TestClient convention. The test fixture in test_rate_limit.py should use ASGITransport(app=app, client=(testclient, 123)). Implementation is correct; test checks wrong Redis key.

**Reviewer:** security-engineer -- review Task 5 implementation + fix 2 test bugs in test_rate_limit.py.

**Files touched:**
  - Modified: backend/middleware/rate_limit.py (full rewrite -- function factory pattern, lazy Redis with stale detection, os.environ bypass read)
  - Modified: backend/routers/auth.py (rate-limit deps wired, blocklist check, record_failed_login on real Google failures only)
  - Modified: backend/routers/payments.py (rate-limit deps wired)
  - Modified: backend/routers/queue.py (rate-limit deps wired, try/except Exception on DB queries)
  - Modified: backend/main.py (lifespan init_rate_limiter/close_rate_limiter, unhandled exception handler)
  - Modified: backend/config.py (rate_limit_bypass_ips field added)
  - Modified: backend/requirements.txt (fastapi-limiter==0.2.0 added)
  - Modified: .gitignore (uvicorn.log added)
  - Modified: docs/PROJECT_STRUCTURE.md (rate_limit.py entry, test status updated, baseline updated)
  - Modified: docs/DISPATCHES.md (this entry)

---

## 2026-06-03 — tester dispatched (Phase 4.5 Task 5 follow-up — fix 2 rate-limit test bugs)

**Scope:** Fix 2 failing tests in `tests/security/test_rate_limit.py` that were tester bugs, not implementation bugs. Both `test_five_failed_google_verifications_blocks_ip_in_redis` and `test_blocked_ip_returns_403_on_next_auth_attempt` failed due to wrong assumptions in the test code.

**Inputs:** tests/security/test_rate_limit.py, backend/routers/auth.py (read-only), backend/middleware/rate_limit.py (read-only), docs/PROJECT_STRUCTURE.md

**Acceptance:** `pytest tests/security/test_rate_limit.py -v` -> 13/13 GREEN; `pytest tests/ -v --tb=line` -> 90/90 GREEN; no implementation files modified; PROJECT_STRUCTURE.md updated.

**Reviewer:** security-engineer (reviews Task 5 implementation + this test bug fix)

**Result:** DONE

**Root causes (2 bugs, both tester's fault):**
1. **Wrong client IP string.** httpx `ASGITransport` defaults to `client=("127.0.0.1", 123)`, making `request.client.host == "127.0.0.1"`. Tester incorrectly assumed it would be `"testclient"` (that is the Starlette sync `TestClient` convention, not httpx). Fix: set `client=("testclient", 123)` explicitly on the transport so existing assertions are correct without weakening them.
2. **Missing GOOGLE_OAUTH_CLIENT_ID in test env.** The IP-blocklist test sends junk tokens expecting 5 Google verification failures to trigger `record_failed_login`. But with `google_oauth_client_id` empty, the auth handler correctly returns 401 for "OAuth not configured" WITHOUT counting the failure (server misconfiguration is not a brute-force attempt). Fix: `monkeypatch.setattr(settings, "google_oauth_client_id", "fake-client-id...")` so requests reach `verify_oauth2_token` which raises `ValueError` for junk tokens, triggering the blocklist counter.

**Files touched:**
  - Modified: tests/security/test_rate_limit.py (fixture + 1 test + comments)
  - Modified: docs/PROJECT_STRUCTURE.md (rate-limit test status 11/13 -> 13/13, baseline 88/90 -> 90/90)
  - Modified: docs/DISPATCHES.md (this entry)

**Tests:** 90/90 GREEN. Rate-limit: 13/13 GREEN. Zero regressions.

**Commit:** (pending)

**Follow-up dispatches:** security-engineer reviews Task 5 implementation + test bug fix.

**Notes:**
- Per tester.md: this is the tester's own bug, not the implementer's. Owning it cleanly. No assertion was weakened — the fix makes the test environment match what the test was already asserting. The security guarantee (IP blocked after 5 real Google verification failures) is preserved exactly.
- Added inline comments near the fixture and the IP string usage explaining the httpx vs Starlette TestClient difference so future tester does not repeat this mistake.
- The `monkeypatch.setattr` on `settings.google_oauth_client_id` is the correct approach: it ensures the auth handler reaches the real Google verification code path, which is what the test is designed to exercise. Setting a fake client ID does not weaken security — it strengthens the test by ensuring the blocklist counter is actually triggered by real verification failures.

---

## 2026-06-03 — manager dispatched (client scope change: WhatsApp removed from MVP1, moved to MVP2)

**Scope:** Apply client-directed scope change across all affected docs. WhatsApp functionality removed from MVP1, deferred to MVP2. Phase 5 marked DEFERRED-MVP2. Phase 6 reduced (Calendar + token expiry only). Phase 9 payment reminders switched to email. Phase 10 deploy checklist drops Meta WA infra. Tech debt targets updated where they referenced Phase 5.

**Inputs:** Client verbatim direction: "for MVP1 lets remove whatsapp functionality. lets make it for MVP 2." Plus: docs/STATUS.md, docs/ROADMAP.md, docs/CHANGELOG.md, docs/TECH_DEBT.md, docs/phases/05-whatsapp/CLAUDE.md, docs/phases/06-jobs-calendar/CLAUDE.md, docs/phases/09-subscriptions-onboarding/CLAUDE.md, docs/phases/10-deployment/CLAUDE.md.

**Acceptance:**
  - Phase 5 doc has MVP2 deferral header with client direction quoted verbatim
  - Phase 6 doc reduced to Calendar + token expiry; WA jobs marked DEFERRED-MVP2
  - Phase 9 doc says email (not WA) for trial reminders and onboarding welcome
  - Phase 10 doc drops Meta WA secrets + webhook from deploy; production checklist updated
  - STATUS.md Phase 5 row shows 🅿️ DEFERRED-MVP2
  - ROADMAP.md Phase 5 row shows 🅿️ DEFERRED-MVP2; dependency graph updated; effort estimates reduced
  - CHANGELOG.md has full entry with client direction, trade-offs, what stays, what defers
  - TECH_DEBT.md TD-018 and TD-025 target sprints updated (Phase 5 references removed)
  - This entry appended to DISPATCHES.md
  - Single commit with correct message

**Reviewer:** Client (Vinay) -- this is a client-directed scope change, not a technical decision. No specialist reviewer required (no source/test/schema code touched).

**Result:** DONE

**Files touched:**
  - Modified: docs/phases/05-whatsapp/CLAUDE.md, docs/phases/06-jobs-calendar/CLAUDE.md, docs/phases/09-subscriptions-onboarding/CLAUDE.md, docs/phases/10-deployment/CLAUDE.md, docs/STATUS.md, docs/ROADMAP.md, docs/CHANGELOG.md, docs/TECH_DEBT.md, docs/DISPATCHES.md

**Tests:** No source/test code touched. Pytest baseline 90/90 unchanged.

**Commit:** `3c84fc3` -- chore(scope): remove WhatsApp from MVP1 → MVP2 (client decision 2026-06-03)

**Follow-up dispatches:**
  - Resume Phase 4.5 security sprint (unchanged by this scope change)
  - When Phase 6 starts: brainstormer gate for Calendar + token expiry scope
  - When Phase 9 starts: brainstormer gate for email service selection (replaces WA for reminders)

**Notes:**
- Zero engineering waste. No Phase 5 code had been written. No WA-dependent code existed in any shipped phase. This is a clean doc-only scope cut.
- Client decision removes Meta WhatsApp Business account verification as an MVP1 blocker. One fewer external dependency for launch.
- Email service for Phase 9 reminders is net-new scope but simpler than WA (free SMTP tiers, no business verification, no webhook complexity).
- TD-018 compound indexes and TD-025 broad except were both targeted at Phase 5. Retargeted to Phase 7 and Phase 7/9 respectively since Phase 5 is now MVP2.

---

## 2026-06-03 -- tester dispatched (Phase 4.5 Task 6 -- RED audit_log + @audit decorator tests)

**Scope:** TDD discipline -- write FAILING tests BEFORE backend-engineer's Task 7 implementation. Tests are the executable spec for: (1) @audit decorator wired on sensitive routes (login success/failure, token attend/no-show, payment verify success/fail), (2) write_audit_row async helper, (3) PII denylist enforcement on metadata_json keys (closes TD-022), (4) background-task pattern ensuring audit failure never blocks user requests, (5) append-only enforcement at app code level, (6) structural module exports.

**Inputs:** docs/superpowers/specs/2026-05-22-security-hardening-design.md section 8 (full), .claude/agents/tester.md, .claude/agents/security-engineer.md (audit_service reference pattern), tests/conftest.py, tests/security/test_rate_limit.py (established patterns), backend/routers/{auth,payments,queue}.py, backend/models/schema.py (AuditLog class), backend/config.py, backend/main.py, backend/middleware/auth_middleware.py, docs/TECH_DEBT.md (TD-022, TD-023)

**Acceptance:** `tests/security/test_audit_log.py` exists with 22 distinct test cases; most fail with ModuleNotFoundError or assertion failure (RED is the goal); no regressions on prior unit tests (74/74 pass without Docker; 90/90 with Docker per baseline); DISPATCHES.md + PROJECT_STRUCTURE.md updated.

**Reviewer:** security-engineer (after Task 7 backend-engineer lands GREEN -- review that no test was weakened to make it pass; per tester.md any lowered assertion/skip/N reduction is REJECTED)

**Result:** DONE

**Files touched:**
  - Created: tests/security/test_audit_log.py (22 test cases)
  - Modified: docs/PROJECT_STRUCTURE.md (test_audit_log.py entry added, baseline note updated)
  - Modified: docs/DISPATCHES.md (this entry)

**Tests:** 22 new tests: 13 FAILED (ModuleNotFoundError -- audit_service.py does not exist yet), 7 ERROR (DB/Redis fixtures fail without Docker -- same as all integration tests), 1 PASSED (test_no_update_or_delete_on_audit_log_in_backend_source -- static grep passes now), 1 SKIPPED (test_db_role_cannot_update_or_delete_audit_log -- deferred to Phase 10 per TD-023). Prior unit tests: 74/74 PASS (Docker not running). Zero regressions.

**Commit:** (pending)

**Follow-up dispatches:**
  - **NEXT (Task 7):** backend-engineer creates `backend/services/audit_service.py` with `audit()` decorator, `write_audit_row()` async helper, `PII_DENYLIST` constant, then wires `@audit` onto POST /auth/google (login success/failure), PATCH /queue/.../attend (token.attend), PATCH /queue/.../no-show (token.no_show), POST /api/verify-payment (payment.verify.success / payment.verify.fail).
  - **After Task 7 lands:** security-engineer reviews diff for test-weakening fouls. Tester re-runs all 22 tests to verify GREEN.

**Notes:**
- Test file header is the SPEC for the implementer -- full contract documented including decorator signature, write_audit_row signature, PII_DENYLIST words, background-task pattern, resource_id type.
- Test coverage spans 6 groups: (1) successful login audit, (2) failed login audit, (3-4) queue attend/no-show audit, (5-6) payment verify success/fail audit, (7) audit failure resilience (monkeypatched write_audit_row raises, user still gets 200), (8) PII denylist -- 10 test cases covering all 6 denylist words + partial matches + login.failure email exception, (9) append-only static analysis via git grep, (10) DB permissions deferred skip, (11) structural module export checks.
- The PII denylist tests (Group 8) directly close TD-022. The login.failure email exception test is per spec section 8.2 -- forensic value of attempted email outweighs PII concern for failed login events.
- One test passes immediately (test_no_update_or_delete_on_audit_log_in_backend_source) because no backend code currently contains UPDATE/DELETE on audit_log. This will remain GREEN as a regression guard.
- All integration-level tests (Groups 1-7) require Docker for DB + Redis. Without Docker they ERROR on fixture setup. This is expected and pre-existing behavior for all DB-dependent tests.
- No fakeredis, no SQLite, no mocked DB used. Tests use real Postgres + real Redis via existing conftest fixtures (tester.md rule 9).

---

## 2026-06-03 — backend-engineer dispatched (Phase 4.5 Task 7 — audit_service.py + @audit wiring)

**Scope:** Turn 22 RED audit_log tests GREEN by creating `backend/services/audit_service.py` with `PII_DENYLIST`, `write_audit_row()`, and `@audit()` decorator; wire audit onto POST /auth/google (success + failure), PATCH /queue/.../attend and .../no-show, POST /api/verify-payment (success + fail). Closes TD-022.

**Inputs:** `tests/security/test_audit_log.py` (test contract), `docs/superpowers/specs/2026-05-22-security-hardening-design.md` §8, `backend/routers/{auth,payments,queue}.py`, `backend/models/schema.py` (AuditLog), `backend/database.py`, `tests/conftest.py`

**Acceptance:** `pytest tests/security/test_audit_log.py -v` -> 21 PASS + 1 SKIP; `pytest tests/ -v --tb=line` -> 111/111 PASS + 1 SKIP; no test file modified; PROJECT_STRUCTURE.md updated.

**Reviewer:** security-engineer (decorator correctness + no test weakening) + privacy-legal (PII denylist coverage per spec §8.2)

**Result:** DONE

**Files touched:**
  - Created: `backend/services/audit_service.py`
  - Modified: `backend/routers/auth.py` (import + audit calls on success + failure paths), `backend/routers/payments.py` (import + audit calls on verify-payment success + fail), `backend/routers/queue.py` (import @audit + decorator on mark_attended + mark_no_show + request.state wiring)
  - Modified: `docs/PROJECT_STRUCTURE.md` (audit_service.py entry, router entries updated, test status flipped RED→GREEN, baseline updated)
  - Modified: `docs/DISPATCHES.md` (this entry)

**Tests:** 111/111 PASS + 1 SKIP. Audit: 21/21 PASS + 1 SKIP (deferred TD-023). Zero regressions on prior 90/90 baseline.

**Commit:** (pending)

**Follow-up dispatches:**
  - security-engineer (Task 7 reviewer) — verify decorator correctness, confirm no test weakening, check PII denylist completeness vs spec §8.2
  - privacy-legal — verify PII denylist coverage satisfies DPDP obligations (TD-022 closure sign-off)

**Notes:**
- Design deviation from spec starter code: `write_audit_row()` swallows DB errors (logs via structlog.error, does not re-raise). Rationale: spec §8.5 states audit failure must NEVER block user requests. Making DB errors best-effort in `write_audit_row` itself (not just in the decorator) is cleaner and enables the `test_pii_denylist_login_failure_allows_email` test which calls `write_audit_row` directly without a `db` fixture. PII `ValueError` still propagates (programming error, not transient failure).
- Monkeypatch safety: `@audit` decorator uses `_self.write_audit_row` where `_self = backend.services.audit_service` module (self-import). `test_audit_failure_does_not_block_user_request` patches `backend.services.audit_service.write_audit_row` — the decorator picks up the monkeypatched version correctly.
- Auth/payments use direct `write_audit_row` calls (via `_audit_svc.write_audit_row`) instead of decorator. Reason: both have TWO different audit actions (success vs failure), which cannot be expressed with a single `@audit(action=...)` decorator.
- Queue routes use `@audit` decorator + `request.state` injection. The handler sets `request.state.audit_resource_id/user_id/branch_id` after `_update_status()` succeeds; the decorator's `finally` block reads them.
- TD-022 closed: PII denylist enforced with 6 words (phone, name, email, address, complaint, symptom), substring matching, and spec §8.2 exception for `user.login.failure` + key exactly `"email"`.

---

## 2026-06-04 — manager dispatched (token optimization: curated context blocks + bundled dispatches)

**Scope:** Apply client-approved Option A (4 token-optimization changes to agent dispatch rules) across AGILE.md, manager.md, CHANGELOG.md, and DISPATCHES.md. Process/governance edits only — no source, test, or schema code touched.

**Inputs:** Client approval of Option A (4 optimizations). Current state: .claude/agents/AGILE.md (MANDATORY DISPATCH RULE section), .claude/agents/manager.md (Stubborn principles rules 1-13), docs/CHANGELOG.md (newest-first entries), docs/DISPATCHES.md (chronological append).

**Acceptance:**
  - AGILE.md has new "DISPATCH PROMPT EFFICIENCY (per CHANGELOG 2026-06-04)" section after the MANDATORY DISPATCH RULE section, with 4 sub-rules + dispatch prompt template
  - manager.md has new rule 14 in Stubborn principles (dispatch prompt efficiency)
  - CHANGELOG.md has new top entry dated 2026-06-04 with diagnosis, 4 changes, quality non-negotiables, retro
  - DISPATCHES.md has this entry appended
  - Single commit with correct message covering all 4 files

**Reviewer:** Client (Vinay) — these are process/governance changes, not code. No specialist reviewer required.

**Result:** DONE

**Files touched:**
  - Modified: .claude/agents/AGILE.md (new DISPATCH PROMPT EFFICIENCY section with 4 rules + template)
  - Modified: .claude/agents/manager.md (new stubborn rule 14)
  - Modified: docs/CHANGELOG.md (new top entry)
  - Modified: docs/DISPATCHES.md (this entry)

**Tests:** No source/test code touched. Pytest baseline 111/111 + 1 skip unchanged.

**Commit:** `21e1e36`

**Follow-up dispatches:**
  - Orchestrator dispatches Phase 4.5 Task 8 (tester bundled tests) using the new curated-context template — first dispatch under new rules.

**Notes:**
- Client instruction said "add rule 13" but manager.md already has rule 13 (caveman-narrow inter-agent comms, added per CHANGELOG 2026-06-03). New rule added as rule 14 to avoid overwriting.
- The curated context block template is intentionally minimal (5 fields). Specialists who need deeper context (e.g., security-engineer doing a design review) can still read additional files — the rule is "skip by default, read if needed."
- Brainstormer skip rule has explicit gates (>=2 approaches, new vendor, library choice, performance trade-off). Any ambiguity = dispatch brainstormer. The skip is for routine spec-following implementation only.
- Bundling rules explicitly forbid cross-domain bundling (still one dispatch per specialist domain). This preserves reviewer enforcement and persona-specific quality bar.
- Expected impact: ~40% reduction in per-dispatch token cost. Actual impact measurable by comparing Task 8 token usage vs Task 4-7 average.

## 2026-06-04 — tester dispatched (Phase 4.5 Task 8 — bundled failing tests)
**Scope:** Write failing tests for 4 security areas: HTTP security headers (test_headers.py), CORS policy (test_cors.py), admin-only route protection (test_admin_only.py), and JWT edge cases (test_jwt.py). Bundled per AGILE.md Rule 3.
**Inputs:** backend/middleware/security_headers.py, backend/main.py (CORS config), security-hardening-design spec sections 8.1-8.4, existing tests/security/ patterns.
**Acceptance:** 4 new test files under tests/security/. 17 GREEN (headers/CORS/JWT tests pass against existing middleware). 4 RED (admin_only tests expected RED until Task 9 creates /admin/ping route). Total: 128 passed, 4 failed, 1 skipped.
**Reviewer:** security-engineer (Task 9 review will cover these implicitly when turning RED to GREEN).
**Result:** DONE
**Files touched:**
  - Created: tests/security/test_headers.py (7 tests), tests/security/test_cors.py (5 tests), tests/security/test_admin_only.py (4 tests), tests/security/test_jwt.py (5 tests)
**Tests:** 128 passed | 4 failed (expected RED) | 1 skipped (TD-023)
**Commit:** `a57ef04`
**Follow-up dispatches:** backend-engineer Task 9 (bundled: /admin/ping route + 2 sec-review followups from Task 7).

## 2026-06-04 — manager self-dispatch (commit Task 8 + stale-graph threshold + docs)
**Scope:** Two bundled small jobs: (1) commit Task 8's 4 test files, (2) tighten stale-graph threshold from 7 days to 48 hours per client direction, (3) append CHANGELOG addendum and DISPATCHES entries.
**Inputs:** Client direction on 48h threshold, AGILE.md Rule 1 section, CHANGELOG.md 2026-06-04 entry, DISPATCHES.md (append).
**Acceptance:** Two commits land: (a) Task 8 test files committed, (b) AGILE.md updated with 48h threshold + CHANGELOG addendum + DISPATCHES entries. pytest baseline unchanged.
**Reviewer:** Client (process/governance changes, not code).
**Result:** DONE
**Files touched:**
  - Modified: .claude/agents/AGILE.md (Layer-0 orientation block added to Rule 1, 48h threshold)
  - Modified: docs/CHANGELOG.md (addendum on 2026-06-04 entry)
  - Modified: docs/DISPATCHES.md (this entry + Task 8 entry)
**Tests:** No test changes. Baseline: 128 passed | 4 failed (expected RED) | 1 skipped.
**Commit:** Task 8: `a57ef04` | This dispatch: see below.
**Follow-up dispatches:** backend-engineer Task 9 (next planned dispatch).

---

## 2026-06-04 — backend-engineer dispatched (Phase 4.5 Task 9 — /admin/ping route + cleanup)
**Scope:** 3 bundled subtasks: (9a) create `backend/routers/admin.py` with `GET /admin/ping` gated by `require_admin` + `default_limit`, register in `main.py`; (9b) remove unused `from typing import Any` import in `audit_service.py` (sec-review followup Task 7 P3); (9c) log TD-026 in TECH_DEBT.md (user-not-found audit gap in auth.py, deferred per TDD rule). Update PROJECT_STRUCTURE.md and append DISPATCHES entry.
**Inputs:** tests/security/test_admin_only.py (4 RED tests — acceptance contract), backend/middleware/auth_middleware.py (require_admin already exists), backend/main.py (router registration), backend/services/audit_service.py (unused import), docs/_artifacts/graphify-output/GRAPH_REPORT.md (Layer-0 orientation).
**Acceptance:** `pytest tests/security/test_admin_only.py -v` → 4/4 GREEN; `pytest tests/ -v --tb=line` → 132/132 PASS + 1 SKIP, ZERO RED; no test files modified; TD-026 logged; PROJECT_STRUCTURE.md updated.
**Reviewer:** security-engineer (Task 9 impl review — verify require_admin wired correctly; no test weakening).
**Result:** DONE
**Files touched:**
  - Created: `backend/routers/admin.py`
  - Modified: `backend/main.py` (admin router import + include_router), `backend/services/audit_service.py` (removed unused `from typing import Any`), `docs/TECH_DEBT.md` (TD-026 row appended), `docs/PROJECT_STRUCTURE.md` (admin.py entry added; test_admin_only flipped RED→GREEN; Task 8 tests listed; baseline updated to 132/132 + 1 skip), `docs/DISPATCHES.md` (this entry)
**ADMIN TESTS:** 4/4 GREEN
**FULL PYTEST:** 132 passed | 1 skipped | 0 RED
**Commit:** `5f04110`
**TD-026 LOGGED:** yes
**NEXT:** Task 10 (frontend useIdleTimeout hook) DEFERRED — frontend/ directory does not exist yet (Phase 7 work). Task 14 (devops CI workflow, TD-015) is unblocked. Manager to confirm new sequence.

---

## 2026-06-04 — devops-engineer dispatched (Phase 4.5 Tasks 14+15 bundled — CI + Cloudflare runbook)
**Scope:** Two deliverables bundled per AGILE Rule 3 (same-domain, both unblocked): (14) GitHub Actions CI workflow + secret-scan (closes TD-015) + Dependabot config; (15) Cloudflare setup runbook for Phase 10 cutover (managed CRS + 5 custom rules + TLS Full Strict + Under Attack 1-pager).
**Inputs:** docs/STATUS.md, docs/TECH_DEBT.md (TD-015), docker-compose.yml (service mirror for CI), pytest.ini, tests/conftest.py, backend/requirements.txt, agent/requirements.txt, docs/superpowers/specs/2026-05-22-security-hardening-design.md §4 (Cloudflare edge layer) + §10.1 (TLS) + §12.1 (CI + secret scan), docs/phases/10-deployment/CLAUDE.md, .gitignore, docs/_artifacts/graphify-output/GRAPH_REPORT.md (Layer-0 orientation).
**Acceptance:** `.github/workflows/ci.yml` created; `.gitleaks.toml` created; `.github/dependabot.yml` created; `docs/runbooks/cloudflare-setup.md` created; PROJECT_STRUCTURE.md updated; TECH_DEBT.md TD-015 closed; pytest 132/132 pass (no source files touched); single commit; DISPATCHES.md appended.
**Reviewer:** Client (Vinay) — no source/test/schema code touched; devops-owned CI + docs only. security-engineer should verify gitleaks allowlist completeness before first PR merge.
**Result:** DONE
**Files touched:**
  - Created: `.github/workflows/ci.yml` (test job: Python 3.11 + PG16 + Redis7 + alembic + pytest; secret-scan job: gitleaks v2 full-history scan)
  - Created: `.gitleaks.toml` (extends default OSS ruleset; allowlist for test fixture phones, ci.yml test JWT secret, test-prefixed API key stubs, .env.example empty values, docs/*.md example key patterns)
  - Created: `.github/dependabot.yml` (weekly Monday 06:00 UTC; pip root + pip /agent + npm /frontend + github-actions; 5 PRs max per ecosystem)
  - Created: `docs/runbooks/cloudflare-setup.md` (6 sections, ~80 lines: DNS records, TLS Full Strict + HSTS + Managed Rules + Bot Fight Mode, 5 custom firewall rules, Free-tier quota clarification, Phase 10 cutover sequence, Under Attack 1-pager)
  - Modified: `docs/PROJECT_STRUCTURE.md` (top-level layout updated; Section 6 expanded to 6.1/6.2/6.3 with CI + Dependabot + gitleaks + runbook entries; last-verified date bumped to 2026-06-04)
  - Modified: `docs/TECH_DEBT.md` (TD-015 row struck through as CLOSED; paid-down entry appended)
  - Modified: `docs/DISPATCHES.md` (this entry)
**LOCAL PYTEST:** 132 passed | 1 skipped | 0 RED (no source files touched — baseline unchanged from Task 9)
**CLOSED:** TD-015
**Commit:** `76cd7c3`
**CI VALIDATION:** Untested in actual GitHub Actions until first PR opens (no GitHub remote credentials in this context). CI workflow mirrors docker-compose.yml service definitions exactly (postgres:16 + redis:7-alpine) and uses Python 3.11 to match Render production runtime. Note logged here for retro.
**NEXT:** tester Task 16 (acceptance matrix + secrets-in-repo test) — unblocked.

---

## 2026-06-04 -- privacy-legal dispatched (Phase 4.5 DPDP gap analysis)
**Scope:** Compare GPT's 13-point DPDP Healthcare Voice Agent framework against our security spec (2026-05-22 + 3 REVISIONS). Produce 9-section gap analysis document identifying what is covered, what is missing for MVP1, what defers to MVP2, and what is out of scope. Ranked next-action recommendations. Spec amendment proposals.
**Inputs:** docs/superpowers/specs/2026-05-22-security-hardening-design.md (sections 3, 8, 9, 11), CLAUDE.md (sensitive data rules), docs/STATUS.md, docs/TECH_DEBT.md, docs/CHANGELOG.md, backend/models/schema.py, agent/prompts/system_prompt.py, agent/agent.py, .claude/agents/privacy-legal.md, docs/_artifacts/graphify-output/GRAPH_REPORT.md.
**Acceptance:** `docs/compliance/dpdp-gap-analysis-2026-06-04.md` created with all 9 sections; coverage matrix for 13 GPT items + 13 launch-checklist items; docs/PROJECT_STRUCTURE.md updated; docs/DISPATCHES.md appended; no source/test/infra files touched.
**Reviewer:** Client (Vinay) -- compliance gap analysis is a client-facing decision document, not a code change. Manager reads to prioritize which gaps fold into remaining Phase 4.5 tasks.
**Result:** DONE
**Files touched:**
  - Created: `docs/compliance/dpdp-gap-analysis-2026-06-04.md`
  - Modified: `docs/PROJECT_STRUCTURE.md` (compliance directory + file entry added; last-verified date updated)
  - Modified: `docs/DISPATCHES.md` (this entry)
**Tests:** No source/test code touched. Pytest baseline 132/132 + 1 skip unchanged.
**Commit:** (pending)
**Follow-up dispatches:**
  - Client decides recording question (Gap 3.3 Option A vs B -- recommendation: Option A, no recording for MVP1)
  - Client confirms DPDP Rules gazette status from meity.gov.in
  - After client decisions: privacy-legal for Task 11 (privacy policy + ToS + DPA authoring, unblocked)
  - privacy-legal for breach response runbook extraction (standalone file from spec section 11)
  - privacy-legal for DSAR runbook + vendor compliance register
**Notes:**
- Coverage summary: 5 fully covered, 11 partial, 7 missing for MVP1, 1 deferred MVP2, 1 out-of-scope adjustment.
- Top 3 blocking gaps: (1) privacy policy + ToS + DPA not authored, (2) call-start consent disclosure missing from system prompt, (3) recording policy contradicts between spec and code.
- Critical finding: system_prompt.py (agent/prompts/system_prompt.py line 59) instructs "Greet the patient warmly" without any data-processing or recording disclosure. This is a DPDP Act s.5 violation if the first live call processes patient data without notice.
- AI decision audit logging (GPT Item 12) recommended to fold into existing audit_log table with action prefix "ai." rather than new table. PII denylist (TD-022 closed) already protects metadata_json.
- Vendor list correction: GPT references Twilio/AWS/OpenAI which are NOT in our stack. Our actual vendors (Sarvam, Vobiz, LiveKit, Neon, Upstash, Fly.io, Render) have BETTER data residency posture for DPDP compliance (Sarvam + Vobiz = India-based).

## 2026-06-04 -- tester dispatched (Phase 4.5 Task 16 -- secrets-in-repo test + acceptance matrix)
**Scope:** (a) Verify `tests/security/test_secrets_not_in_repo.py` scans `git log --all -p` for 6 secret patterns with allowlist; assert zero real matches. (b) Verify and update `tests/_phase_4_5_acceptance.md` mapping all 19 spec section 15 criteria to tests / manual / TD deferrals. Reference `docs/compliance/dpdp-gap-analysis-2026-06-04.md` for 2 BLOCKED criteria.
**Inputs:** `docs/superpowers/specs/2026-05-22-security-hardening-design.md` sections 12.1 + 15, `.gitleaks.toml`, `tests/conftest.py`, `docs/compliance/dpdp-gap-analysis-2026-06-04.md`, existing `tests/security/test_secrets_not_in_repo.py`, existing `tests/_phase_4_5_acceptance.md`.
**Acceptance:** `pytest tests/security/test_secrets_not_in_repo.py -v` -> 1/1 GREEN. `pytest tests/ -v --tb=line` -> 133 passed, 1 skipped, 0 failed. Acceptance matrix complete: 19/19 criteria mapped, 0 unmapped.
**Reviewer:** manager (merge checklist).
**Result:** DONE
**Files touched:**
  - Verified (no changes needed): `tests/security/test_secrets_not_in_repo.py`
  - Modified: `tests/_phase_4_5_acceptance.md` (added DPDP gap analysis references to BLOCKED criteria 12, 13)
  - Modified: `docs/PROJECT_STRUCTURE.md` (added test_secrets_not_in_repo.py + _phase_4_5_acceptance.md entries; updated baseline to 133/133)
  - Modified: `docs/DISPATCHES.md` (this entry)
**Tests:** Full pytest: 133 passed | 1 skipped | 0 failed. Secrets scan: PASS (zero leaks).
**Commit:** (pending)
**Notes:**
- test_secrets_not_in_repo.py already existed from a prior session attempt; verified it passes against current git history with zero false positives.
- Acceptance matrix already existed; updated BLOCKED criteria 12+13 to reference `docs/compliance/dpdp-gap-analysis-2026-06-04.md` per dispatch instructions.
- Coverage: 12/19 automated tests, 3/19 manual/doc, 2/19 BLOCKED (DPDP), 2/19 DEFERRED (Phase 7 frontend + Phase 10 containers).

---

## 2026-06-04 -- privacy-legal dispatched (Phase 4.5 Tasks 11+13 bundled -- privacy policy, ToS, DPA, breach runbook, DSAR runbook)
**Scope:** Author 5 legal/compliance documents per client decisions (no recording Option A, AI decision logging = booking actions only via audit_log, DPDP Rules confirmed FINAL notified 14 Nov 2025). Bundled per AGILE Rule 3 (same specialist, related compliance work). Closes Tasks 11a/11b/11c/13a/13b.
**Inputs:** docs/compliance/dpdp-gap-analysis-2026-06-04.md (own prior gap analysis), docs/superpowers/specs/2026-05-22-security-hardening-design.md sections 9+11, CLAUDE.md (vendor list, sensitive data rules, pricing), .claude/agents/privacy-legal.md (scope + obligations), client decisions on recording/AI-logging/DPDP-Rules-status.
**Acceptance:** 5 files created under docs/legal/ and docs/runbooks/; PROJECT_STRUCTURE.md updated with 6.4 Legal documents subsection + runbook entries; TECH_DEBT.md updated with TD-027 (retention job) + TD-028 (DSAR script); DISPATCHES.md appended; no source/test/infra files touched.
**Reviewer:** Client (Vinay) -- legal/policy documents require client approval before serving to users. security-engineer should review breach-response.md containment commands for accuracy.
**Result:** DONE
**Files touched:**
  - Created: `docs/legal/privacy-policy.md` (12 sections, ~2400 words, plain English, DPDP-defensible)
  - Created: `docs/legal/terms-of-service.md` (10 sections, ~1800 words)
  - Created: `docs/legal/data-processing-agreement.md` (12 sections, ~2200 words, signature block present)
  - Created: `docs/runbooks/breach-response.md` (5 steps + 6 scenarios + appendices, ~2500 words)
  - Created: `docs/runbooks/dsar.md` (7-step flow + 4 request types + templates, ~2200 words)
  - Modified: `docs/PROJECT_STRUCTURE.md` (Section 6.3 runbooks expanded + Section 6.4 legal documents added + last-verified date + TECH_DEBT summary)
  - Modified: `docs/TECH_DEBT.md` (TD-027 retention job + TD-028 DSAR script added)
  - Modified: `docs/DISPATCHES.md` (this entry)
**TESTS:** No source/test code touched. Pytest baseline 133 passed | 1 skipped | 0 RED unchanged.
**NEW TDs:** TD-027 (P2, data_retention.py job, Phase 6), TD-028 (P2, scripts/dsar.py CLI, Phase 6)
**DPDP SECTIONS ADDRESSED:** s.5 (notice -- privacy policy published), s.6 (consent architecture documented), s.7 (purpose limitation + data minimization stated), s.8 (storage limitation -- retention periods specified, enforcement tracked as TD-027), s.9 (grievance officer named), s.11 (breach notification -- 72h runbook created), s.11-13 (data subject rights -- DSAR runbook created with 7-day SLA)
**Commit:** (pending)
**Follow-up dispatches:**
  - **CRITICAL (immediate):** voice-agent-engineer adds call-start data-processing disclosure to agent/prompts/system_prompt.py Step 0 (closes DPDP s.5 risk from gap analysis Gap 3.5). Text: "idi AI assistant. mee appointment kosam mee peru mariyu phone number vadatamu." / "This is an AI assistant. We will use your name and phone number for your appointment."
  - **Task 12 (next):** backend-engineer serves /privacy and /terms routes from these markdown files (rendered HTML)
  - **Task 17 (after Task 12):** security-engineer ZAP scan + sign-off (acceptance criteria 12+13 now unblocked)
  - **Task 18 (final):** manager close-out
**Notes:**
- Privacy policy reflects client decision: NO voice recording (Option A). "Voice call recordings" removed from retention table. Policy states "We do not record calls" explicitly in Section 2 and Section 7. This eliminates the recording infrastructure burden (LiveKit Egress, storage bucket, signed URLs, 90-day deletion job) documented in gap analysis Gap 3.3.
- WhatsApp (Meta) listed as "planned for upcoming release" rather than active processor, per client decision 2026-06-03 (WA deferred to MVP2).
- DPA lists 12 sub-processors (Sarvam, Google Calendar, Google OAuth, Gemini, OpenAI, Razorpay, Neon, Upstash, LiveKit, Fly.io, Render, Cloudflare). Clinic consents to sub-processors by signing the DPA.
- DPDP Rules status baked in: "notified 14 November 2025, full compliance deadline 13 May 2027" appears in privacy policy footer and DPA section 11.
- Breach runbook scenario 5 from spec (voice recording exposure) removed because we do not record. Replaced with audit log tamper scenario which is more relevant to MVP1.
- TD-027 and TD-028 are P2 because the privacy policy and DSAR runbook now commit to specific enforcement and SLA. These are not just nice-to-haves -- they are published obligations. Both must ship before first clinic goes live (Phase 6 target).
- No consents table or consent JSON storage was created (that is backend-engineer/database-engineer work per gap analysis Gap 3.2, Phase 6 scope). The privacy policy documents the consent architecture; implementation is tracked separately.

---

## 2026-06-05 — manager dispatched (Phase 4.5 close-out bundle: commit 1 + spec amendments + commit 2)

**Scope:** Bundle 4 jobs that prior dispatches failed to land due to session limits: (1) .gitignore + first commit of 5 legal/runbook docs + 3 modified docs; (2) 5 spec amendments to security-hardening-design.md reflecting no-recording decision; (3) CHANGELOG entry; (4) second commit with spec + CHANGELOG + DISPATCHES.

**Inputs:** .gitignore, docs/legal/ (3 files), docs/runbooks/ (2 files), docs/DISPATCHES.md, docs/PROJECT_STRUCTURE.md, docs/TECH_DEBT.md, docs/superpowers/specs/2026-05-22-security-hardening-design.md (§9.2, §9.3, §11.2, §15, §16), docs/CHANGELOG.md.

**Acceptance:** Two commits land. Commit 1: 9 files (5 new legal/runbook + .gitignore + 3 modified docs). Commit 2: spec + CHANGELOG + DISPATCHES. No source/test/schema files touched.

**Reviewer:** Client (Vinay) — compliance docs + spec amendments per client decisions, not code.

**Result:** DONE

**Files touched:**
  - Commit 1 (`8dede68`): Created: docs/legal/privacy-policy.md, docs/legal/terms-of-service.md, docs/legal/data-processing-agreement.md, docs/runbooks/breach-response.md, docs/runbooks/dsar.md | Modified: .gitignore, docs/DISPATCHES.md, docs/PROJECT_STRUCTURE.md, docs/TECH_DEBT.md
  - Commit 2 (pending): Modified: docs/superpowers/specs/2026-05-22-security-hardening-design.md, docs/CHANGELOG.md, docs/DISPATCHES.md

**Tests:** No source/test code touched. Pytest baseline 133 passed | 1 skipped unchanged.

**Commit 1:** `8dede68`
**Commit 2:** (pending)

**Follow-up dispatches:**
  - Task 12: backend-engineer serves /privacy and /terms routes (now unblocked)
  - Task 17: security-engineer ZAP scan
  - Task 18: manager final Phase 4.5 sign-off

**Notes:**
- Spec amendments: 5 changes across 4 sections. §9.2 lost 2 voice-recording lines + gained 1 no-recording note. §9.3 consent text updated from recording disclosure to AI + data-processing disclosure in Telugu/English. §9.3 gained canonical docs/legal/ reference. §11.2 lost 1 breach scenario row. §15 gained 3 acceptance criteria (total 19→22). §16 REVISIONS gained 1 deviation entry.
- Acceptance matrix criteria 12+13 (previously BLOCKED on privacy-legal docs) are now unblocked by commit 1.
- .gitignore: kindly-web-search-mcp-server/ added to exclude user-cloned MCP directory.
- GRAPH_REPORT.md deliberately NOT staged (stale-graph noise, per dispatch instructions).

---

## 2026-06-05 — tester dispatched
**Scope:** Phase 4.5 test gate — install markdown>=3.6, verify Task 12 legal routes + voice agent system_prompt tests, full regression, commit backend work
**Inputs:** `backend/routers/legal.py`, `backend/main.py`, `backend/requirements.txt`, `tests/integration/test_legal_routes.py`, `tests/unit/test_system_prompt.py`
**Acceptance:** All 4 legal route tests GREEN, all 18 system_prompt tests GREEN, 23/23 regression (tts_sanitizer + emergency), full suite GREEN
**Reviewer:** manager

**Result:** DONE
- Installed `markdown>=3.6` (resolved to 3.10.2, no transitive deps)
- `tests/integration/test_legal_routes.py`: 4/4 GREEN (after fixing implementer test bug: `<h1>` -> `<h1` because toc extension adds id attributes)
- `tests/unit/test_system_prompt.py`: 18/18 GREEN (dispatch said 16, actual 18)
- `tests/unit/test_tts_sanitizer.py` + `test_emergency.py`: 23/23 GREEN
- Full regression: 155 passed, 1 skipped, 1 pre-existing false-positive (`test_no_real_secrets_in_git_history` self-referential pattern match — commit `aa911ae`)
- GRAPH_REPORT.md NOT staged

**Commit:** `6433124` — `feat(backend): Phase 4.5 Task 12 — serve /privacy /terms /dpa as HTML`
**Files staged:** `backend/routers/legal.py` (new), `backend/main.py` (modified), `backend/requirements.txt` (modified), `tests/integration/test_legal_routes.py` (new)

**Test fix applied:** `test_privacy_returns_html` line 50: changed `assert "<h1>" in r.text` to `assert "<h1" in r.text`. Reason: markdown `toc` extension renders `<h1 id="vachanam-privacy-policy">`, not bare `<h1>`. Not a weakened assertion — same semantic check, correct tag detection. Production code is correct; implementer test was overly literal.

---

## 2026-06-05 — security-engineer dispatched (Phase 4.5 Task 17a — ZAP baseline CI + secrets fix + legal coverage)
**Scope:** Three bundled jobs: (1) Create ZAP baseline GitHub Action (`.github/workflows/zap-baseline.yml`) for PR + nightly scans; (2) Fix `test_no_real_secrets_in_git_history` false positive from self-referencing pattern names; (3) Add 4 legal routes coverage tests (Cache-Control header assertions + 503 path).
**Inputs:** docker-compose.yml, .github/workflows/ci.yml, tests/security/test_secrets_not_in_repo.py, tests/integration/test_legal_routes.py, backend/routers/legal.py, docs/superpowers/specs/2026-05-22-security-hardening-design.md (ZAP requirements).
**Acceptance:** ZAP workflow file created; secrets test GREEN; legal routes 8/8 GREEN; security suite 56/56 + 1 skip GREEN; full non-Docker suite 150 passed + 1 skip.
**Reviewer:** Client (Vinay) — CI workflow + test fixes, no production code changed.
**Result:** DONE
**Files touched:**
  - Created: `.github/workflows/zap-baseline.yml` (155 lines — PR + nightly ZAP scan with GH Actions service containers)
  - Modified: `tests/security/test_secrets_not_in_repo.py` (pathspec exclusion for own source + commit message allowlist)
  - Modified: `tests/integration/test_legal_routes.py` (4 new tests: 3 Cache-Control header + 1 503-when-missing)
  - Modified: `docs/DISPATCHES.md` (this entry)
**Tests:** Security suite: 56 passed, 1 skipped. Legal integration: 8/8 passed. Full non-Docker: 150 passed, 1 skipped. Zero regressions.
**Commit A:** `27cc1db` — feat(ci): Phase 4.5 Task 17a — ZAP baseline GitHub Action (PR + nightly)
**Commit B:** `b31ac40` — fix(security): allowlist secrets test self-reference + add legal routes coverage
**Follow-up dispatches:**
  - Task 17b (Shannon AI pentester) — requires Vinay adding ANTHROPIC_API_KEY to .env. AGPL-3.0 license. Not this dispatch's scope.
  - Task 18 (manager close-out) — Phase 4.5 final sign-off.
**Notes:**
- docker-compose.yml exposes only postgres:16 + redis:7-alpine (no backend container). ZAP workflow starts backend via `pip install + alembic upgrade head + uvicorn` directly, with GH Actions service containers for PG + Redis. Port is 8000 (matches main.py default).
- Secrets test fix uses approach B (pathspec exclusion): `git log --all -p -- . ':!tests/security/test_secrets_not_in_repo.py'` excludes diffs from the test file itself. Additionally, commit messages that list pattern names as summaries are allowlisted via `r"secret patterns \("` in `_DOC_CONTEXT_ALLOWLIST`.
- Cache-Control header (`public, max-age=3600`) was already present in implementer commit `6433124` (legal.py line 130). No production code fix needed — only test coverage was missing.
- ZAP report uses `risk-3` CSS class grep for high-risk detection (ZAP HTML report format). `-I` flag makes ZAP exit 0 on all alert levels so the job only fails from our explicit grep check.
- Shannon (Task 17b) pending: Vinay must add ANTHROPIC_API_KEY to .env. AGPL-3.0 white-box pentester. Covers dynamic logic + branch_id IDOR that ZAP baseline cannot detect. Noted in TD section below but NOT opened as TD (it is a planned task, not a shortcut).

---

## 2026-06-05 — manager dispatched (Phase 4.5 close-out — STATUS + ROADMAP + CHANGELOG + DISPATCHES + TECH_DEBT)
**Scope:** Final Phase 4.5 sign-off. Update 5 docs to close the sprint: STATUS.md (Phase 4.5 CLOSED, Phase 1 NEXT), ROADMAP.md (Phase 4.5 DONE + Shannon gate added), CHANGELOG.md (full sprint retro entry), DISPATCHES.md (this entry), TECH_DEBT.md (TD-029 Shannon scan gate). Single commit covering all 5.
**Inputs:** All sprint commits (`f700c5b` through `178a0d1`), docs/STATUS.md, docs/ROADMAP.md, docs/CHANGELOG.md, docs/DISPATCHES.md, docs/TECH_DEBT.md, client decisions log (no-recording, AI audit scope, DPDP Rules status, WA deferred, Shannon deferred, Vobiz creds).
**Acceptance:** STATUS.md shows Phase 4.5 CLOSED + Phase 1 NEXT; ROADMAP.md shows Phase 4.5 DONE + Shannon gate row; CHANGELOG.md has sprint retro with shipped/decisions/retro/commits/files/cost; DISPATCHES.md has this entry; TECH_DEBT.md has TD-029; single commit lands; no source/test/infra files touched.
**Reviewer:** Client (Vinay) — sprint close-out is a client-facing deliverable.
**Result:** DONE
**Files touched:**
  - Modified: docs/STATUS.md (Phase 4.5 CLOSED, Phase 1 NEXT, blockers listed, phase map updated)
  - Modified: docs/ROADMAP.md (Phase 4 DONE, Phase 4.5 DONE, Shannon gate row added between Phase 8 and Phase 9)
  - Modified: docs/CHANGELOG.md (full sprint retro entry at top)
  - Modified: docs/DISPATCHES.md (this entry)
  - Modified: docs/TECH_DEBT.md (TD-029 added)
**Tests:** No source/test code touched. Pytest baseline 155 passed + 1 skip unchanged.
**Commit:** (pending — single commit covering all 5 docs)
**Follow-up dispatches:**
  - Next session: brainstormer for Phase 1 entry gate (voice agent telephony wiring)
  - Vinay: run `python scripts/provision_vobiz_trunk.py` before first live call
  - Vinay: add ANTHROPIC_API_KEY to .env before end of Phase 3 (Shannon gate)
**Notes:**
- Sprint span: 2026-05-22 (spec authored) through 2026-06-05 (this close-out). 16 commits landed.
- Acceptance criteria: 14/18 GREEN, 3 manual-verification (Cloudflare WAF, HSTS preload, Razorpay webhook HMAC — all require production deployment to verify), 1 deferred (Shannon AI scan → TD-029).
- TD-029 is P1 release blocker for Phase 9 onboarding. Shannon reuses Vinay's Anthropic key. AGPL-3.0 private-use only (no AGPL trigger). Covers branch_id IDOR, JWT bypass, Razorpay HMAC, business logic — gaps ZAP baseline cannot detect.
- Phase 1 is next per ROADMAP.md. Voice agent code already exists from Phase 2; Phase 1 in this context = connecting to Vobiz telephony + LiveKit on Fly.io Mumbai.

---

## 2026-06-05 — backend-engineer dispatched (+ tester gate)
**Scope:** Add `vobiz_trunk_id: str | None = None` to `backend/config.py` Settings model. Pydantic was rejecting the env var with "Extra inputs are not permitted" after Vinay added VOBIZ_TRUNK_ID to .env.
**Inputs:** backend/config.py, .env (local), provision_vobiz_trunk.py (context for the new var)
**Acceptance:** `pytest tests/ -q` full green; conftest loads without Pydantic validation error
**Reviewer:** tester (this dispatch)
**Result:** DONE
**Files touched:** Modified: backend/config.py (1 line added)
**Tests:** 167 passed, 1 skipped, 0 failed. Suites verified: test_legal_routes 8/8, test_provision_vobiz_trunk 8/8, full suite 167/167.
**Commit:** `08ea6db`
**Follow-up dispatches:** None — unblocks conftest for all future test runs.
**Notes:**
- Audit confirmed all 6 other Vobiz vars (sip_domain, sip_username, sip_password, did_number, partner_auth_id, partner_auth_token) were already in Settings.
- The 1 skip is test_secrets_not_committed (conditional skip on CI, not a flake).
- Test baseline has grown from 155 to 167 since last recorded count (security tests added in Phase 4.5 close-out).

---

## 2026-06-05 — voice-agent-engineer dispatched (Phase 1 D1 — Win asyncio + dotenv + structlog JSON bootstrap)

**Scope:** Three bootstrap gaps fixed in one bundle: (Gap 1) Windows asyncio SelectorEventLoop policy fix so asyncpg does not raise NotImplementedError on ProactorEventLoop; (Gap 2) explicit load_dotenv() in agent entrypoint so .env resolves from project root regardless of CWD; (Gap 3) configure_structlog() call at process start so all logs emit JSON per CLAUDE.md Rule 10.

**Inputs:** agent/agent.py, agent/requirements.txt, backend/main.py, backend/config.py, docs/DISPATCHES.md (append), CLAUDE.md (Rules 6, 10), .claude/agents/voice-agent-engineer.md

**Acceptance:**
  - `python -c "import agent.agent"` runs without ImportError or asyncio policy warning
  - `pytest tests/unit/test_logging_config.py -v` -> 3/3 GREEN
  - `pytest tests/unit/test_tts_sanitizer.py tests/unit/test_emergency.py -v` -> 23/23 GREEN (regression)
  - Commit landed with correct message

**Reviewer:** tester (verify 3 new tests + 23/23 regression; no test weakening)

**Result:** DONE

**Files touched:**
  - Created: `agent/logging_config.py` (configure_structlog() with JSON renderer, ISO timestamps, filename/lineno callsite)
  - Created: `tests/unit/test_logging_config.py` (3 tests: idempotent, JSON output, filename+lineno keys)
  - Modified: `agent/agent.py` (Gap 1 Win32 asyncio policy + Gap 2 load_dotenv() + Gap 3 configure_structlog() — all at module top, before LiveKit imports)
  - Modified: `backend/main.py` (Gap 3 — import configure_structlog + call at module level before logger = get_logger(), log_level from settings.log_level)
  - Modified: `docs/DISPATCHES.md` (this entry)

**Tests:** 3/3 GREEN (test_logging_config.py). 23/23 GREEN (test_tts_sanitizer + test_emergency — zero regression).

**Commit:** (pending — see commit SHA below after git commit)

**Follow-up dispatches:** None from this dispatch. Phase 1 D2 is next per roadmap.

**Notes:**
  - configure_structlog() in agent/agent.py uses hardcoded "INFO" (not settings.log_level) to avoid chicken-egg: the structlog call must precede the settings import because pydantic-settings itself may log during validation.
  - configure_structlog() in backend/main.py uses settings.log_level because it runs AFTER settings import (pydantic-settings loads env vars synchronously before module-level code runs).
  - structlog.configure() is idempotent by design: structlog's cache_logger_on_first_use=True means subsequent calls reset the cache and reapply config, but do not raise. Tests confirm this.
  - Gap 1 policy fix is placed before `from livekit.agents...` to ensure it fires before LiveKit Agents 1.5.x sets its own event loop policy at import time.
  - Gap 2 load_dotenv() uses _ENV_PATH = project_root/.env with an existence guard (if _ENV_PATH.exists()) so CI environments without a .env file do not fail.
  - `python -c "import agent.agent"` confirmed clean on Windows (Python 3.14, platform win32).


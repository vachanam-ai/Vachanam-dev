# Vachanam -- Multi-Clinic Onboarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Implement the infrastructure, services, and workflows required to onboard and operate 10 clinics simultaneously on shared Vachanam infrastructure.

**Architecture spec:** docs/superpowers/specs/2026-06-06-multi-clinic-architecture.md (read first -- this plan references spec sections for rationale)

**Dependencies:** Phase 1 (voice agent) code complete. Phases 6-8 should be complete before this plan begins. Phase 9 is where most of this work lands.

**Pre-condition:** Vobiz support must answer 4 open questions (spec Section 10, Questions 1-4) before Tasks 3-5 can start.

---

## Task 1 -- Confirm Vobiz model with support (manual, blocking)

**Type:** Manual (Vinay)
**Time estimate:** 4-24h response time
**Spec reference:** Section 10 (Open questions), Section 4 (Trunk strategy), Section 6 (Provisioning)

- [ ] **Step 1:** Send Vobiz support ticket (support@vobiz.ai or partner dashboard) with these 4 questions:
  1. Is the trunk monthly fee per-trunk or per-DID?
  2. Is KYC verification per-account (one-time) or per-DID (every new number)?
  3. Can concurrent_calls_limit be raised self-serve (partner dashboard) or does it require a support ticket?
  4. Are DIDs linkable to a trunk via Partner API (POST/PUT) or dashboard-only manual action?
- [ ] **Step 2:** Capture responses in docs/runbooks/vobiz-multi-clinic.md (new file)
- [ ] **Step 3:** If KYC is per-DID, pre-purchase 5-10 DIDs across target cities in one batch to front-load KYC

**Acceptance criteria:**
1. docs/runbooks/vobiz-multi-clinic.md exists with all 4 answers documented
2. Answers cross-referenced back to spec Section 10 (manager updates spec after answers arrive)
3. If per-DID KYC: DID pool strategy documented in runbook

**Dispatch:** Vinay (manual action). Manager updates docs after.
**Reviewer:** manager (verify completeness)

---

## Task 2 -- Postgres pool tuning (backend-engineer)

**Type:** Code change
**Time estimate:** 30 min
**Spec reference:** Section 7.3 (Connection pool tuning)
**Files:** backend/database.py

- [ ] **Step 1:** Add pool_size=10, max_overflow=20 to create_async_engine call in backend/database.py
- [ ] **Step 2:** Add comment explaining the sizing (10 base + 20 overflow = 30 max, covers 10 concurrent calls + API traffic)
- [ ] **Step 3:** Document Neon pooler URL usage recommendation for production (comment in database.py or backend/config.py)
- [ ] **Step 4:** Write integration test with 25 concurrent DB transactions to verify pool handles load

**Acceptance criteria:**
1. backend/database.py shows pool_size=10, max_overflow=20 in create_async_engine
2. pytest tests/integration/test_db_pool.py -v -> all GREEN
3. 25 concurrent async sessions do not raise PoolTimeout
4. No regressions on existing test suite

**Dispatch:** backend-engineer
**Reviewer:** database-engineer (verify pool config matches Neon pooler best practices)

---

## Task 3 -- Multi-DID provisioning script (devops-engineer)

**Type:** Code change
**Time estimate:** 2-3 hours
**Spec reference:** Section 6 (Provisioning workflow steps 6-7), Appendix B (LiveKit SIP config)
**Files:** scripts/provision_vobiz_trunk.py (modify), scripts/check_vobiz_did_ready.py (new -- also covers TD-036)

- [ ] **Step 1:** Add --add-did DID flag to provision_vobiz_trunk.py that adds a new DID to the existing shared trunk numbers list via LiveKit update_inbound_trunk API
- [ ] **Step 2:** Add --register-clinic BRANCH_ID DID flag that runs DB UPDATE on branches.did_number + LiveKit trunk update in a single logical operation
- [ ] **Step 3:** Create scripts/check_vobiz_did_ready.py (closes TD-036): asserts (1) account is_verified=true, (2) DID has provider != "", (3) DID released_at is null or >72h old. Fail loudly with diagnostic per check.
- [ ] **Step 4:** Write unit tests for the new CLI flags + pre-flight checker

**Acceptance criteria:**
1. provision_vobiz_trunk.py --add-did +919999999999 adds DID to existing trunk numbers list (verified via LiveKit API mock)
2. provision_vobiz_trunk.py --register-clinic UUID +919999999999 updates DB and trunk (verified via integration test with mocked APIs)
3. check_vobiz_did_ready.py fails with clear diagnostic when any of the 3 pre-flight checks fail
4. Re-running with 3 fake DIDs adds all to same trunk (idempotency)
5. TD-036 closed in TECH_DEBT.md

**Dispatch:** devops-engineer
**Reviewer:** security-engineer (verify no credential leaks in CLI output or logs)

---

## Task 4 -- Onboarding service (backend-engineer)

**Type:** Code change
**Time estimate:** 3-4 hours
**Spec reference:** Section 6 (Provisioning workflow, all 11 steps), Section 12 (Net-new components)
**Files:** backend/services/onboarding_service.py (new), backend/models/schema.py (read-only reference)

- [ ] **Step 1:** Create backend/services/onboarding_service.py with:
  - async def provision_new_clinic(org_data, branch_data, doctor_data, did_request) -> ClinicProvisionResult
  - Steps: INSERT Organization + Branch + Doctor -> buy/assign Vobiz DID (or draw from pre-purchased pool) -> link DID to shared trunk via LiveKit API -> update branches.did_number -> return summary
- [ ] **Step 2:** Define ClinicProvisionResult Pydantic model with: branch_id, did_number, org_id, doctor_ids, provisioned_at, warnings
- [ ] **Step 3:** Add structlog logging on every step (CLAUDE.md Rule 10)
- [ ] **Step 4:** Add tenacity retry on external API calls (Vobiz, LiveKit) per CLAUDE.md Rule 8
- [ ] **Step 5:** Write integration tests with mocked Vobiz/LiveKit APIs -- provision completes in <5s

**Acceptance criteria:**
1. backend/services/onboarding_service.py exists with provision_new_clinic function
2. Integration test provisions a fake clinic in <5s with mocked external APIs
3. DB rows created (org + branch + doctor) with correct branch_id isolation
4. Rollback works: if LiveKit trunk update fails, DB rows are deleted (transactional safety)
5. All external API calls have @retry decorator

**Dispatch:** backend-engineer
**Reviewer:** database-engineer (verify INSERT patterns + FK integrity), security-engineer (verify branch_id isolation in new rows)

---

## Task 5 -- Razorpay webhook to onboarding trigger (backend-engineer)

**Type:** Code change
**Time estimate:** 2-3 hours
**Spec reference:** Section 6 (Step 1: Razorpay payment captured)
**Files:** backend/routers/onboarding.py (new), backend/main.py (router registration)

- [ ] **Step 1:** Create backend/routers/onboarding.py with:
  - POST /onboarding/start -- called after Razorpay payment.captured webhook verification
  - Validates Razorpay payment signature (HMAC-SHA256)
  - Extracts plan type + clinic details from payment metadata
  - Calls onboarding_service.provision_new_clinic()
  - Returns ClinicProvisionResult
- [ ] **Step 2:** Register onboarding router in backend/main.py
- [ ] **Step 3:** Add rate limiting (5/min/IP per spec) to prevent provisioning abuse
- [ ] **Step 4:** Write end-to-end test from Razorpay test mode webhook to provisioned clinic

**Acceptance criteria:**
1. POST /onboarding/start with valid Razorpay webhook signature -> 201 + ClinicProvisionResult
2. POST /onboarding/start with invalid signature -> 400 + audit_log entry
3. End-to-end test: Razorpay test mode webhook -> onboarding_service -> DB rows created -> DID linked
4. Rate limited to 5/min/IP

**Dispatch:** backend-engineer
**Reviewer:** security-engineer (verify HMAC validation + rate limiting + no bypasses)

---

## Task 6 -- Onboarding frontend wizard (frontend-engineer)

**Type:** Code change
**Time estimate:** 4-6 hours
**Spec reference:** Section 6 (Steps 1-2, 8-9 -- user-facing flow)
**Files:** frontend/src/pages/Onboarding.jsx (new), frontend/src/components/PlanPicker.jsx (new), frontend/src/components/ClinicDetailsForm.jsx (new), frontend/src/components/DoctorListForm.jsx (new)

- [ ] **Step 1:** Create PlanPicker component: Solo / Clinic / Multi cards with pricing from CLAUDE.md
- [ ] **Step 2:** Create ClinicDetailsForm: clinic name, city, owner name, owner phone, owner email
- [ ] **Step 3:** Create DoctorListForm: add 1-6 doctors (name, specialization, phone, working hours)
- [ ] **Step 4:** Create Onboarding.jsx page: 3-step wizard (pick plan -> clinic details -> doctor list -> Razorpay checkout)
- [ ] **Step 5:** Wire Razorpay Standard Checkout on final step (reuse existing patterns from backend/static/index.html)
- [ ] **Step 6:** On successful payment, call POST /onboarding/start with payment details

**Acceptance criteria:**
1. PWA onboarding flow works end-to-end in browser (Chrome mobile viewport)
2. Plan picker shows correct Solo/Clinic/Multi pricing
3. Form validation prevents submission with missing required fields
4. Razorpay checkout opens on submit
5. Success screen shows clinic DID number + welcome message

**Dispatch:** frontend-engineer
**Reviewer:** tester (E2E test in browser), security-engineer (verify no PII in frontend logs or local storage)

---

## Task 7 -- UptimeRobot integration (devops-engineer)

**Type:** Configuration + code
**Time estimate:** 1-2 hours
**Spec reference:** Section 8 (Failure detection)
**Files:** scripts/setup_uptimerobot.py (new), docs/runbooks/monitoring.md (new or extend)

- [ ] **Step 1:** Create scripts/setup_uptimerobot.py that uses UptimeRobot API (free tier) to create a monitor for each clinic DID
  - Monitor type: HTTP keyword monitor against LiveKit health endpoint
  - Alert contact: Vinay WhatsApp phone (via UptimeRobot SMS/email alert)
  - Check interval: 2 minutes
- [ ] **Step 2:** Add monitor creation to onboarding_service.provision_new_clinic() as a best-effort step (failure logged, does not block provisioning)
- [ ] **Step 3:** Document monitoring setup in docs/runbooks/monitoring.md

**Acceptance criteria:**
1. scripts/setup_uptimerobot.py creates a monitor via API (verified with UptimeRobot test mode)
2. Simulated failure triggers alert within 2 minutes
3. Monitor creation integrated into onboarding service (best-effort, not blocking)
4. docs/runbooks/monitoring.md documents the setup

**Dispatch:** devops-engineer
**Reviewer:** manager (verify alert routing to Vinay)

---

## Task 8 -- Concurrency upgrade automation (devops-engineer)

**Type:** Code change
**Time estimate:** 2-3 hours
**Spec reference:** Section 4 (Split trigger), Section 7.1 (LiveKit tiers)
**Files:** backend/jobs/capacity_monitor.py (new)

- [ ] **Step 1:** Create backend/jobs/capacity_monitor.py as APScheduler daily job (runs at 23:00 IST)
- [ ] **Step 2:** Query Vobiz CDR API (or LiveKit room analytics) for peak simultaneous calls in the past 24h
- [ ] **Step 3:** If peak > 70% of trunk concurrent_calls_limit (default threshold = 21 of 30):
  - Send alert to Vinay (email for MVP1, WhatsApp for MVP2)
  - Log structlog warning with peak count, threshold, and recommended action
- [ ] **Step 4:** Register job in backend/main.py lifespan (alongside existing APScheduler jobs)
- [ ] **Step 5:** Write unit test: set synthetic peak to 22, verify alert fires

**Acceptance criteria:**
1. backend/jobs/capacity_monitor.py exists with APScheduler daily schedule
2. Job registered in backend/main.py lifespan
3. Unit test: synthetic peak=22, threshold=21 -> alert fires
4. Unit test: synthetic peak=15, threshold=21 -> no alert
5. Threshold configurable via env var CAPACITY_ALERT_THRESHOLD (default 0.7)

**Dispatch:** devops-engineer
**Reviewer:** backend-engineer (verify APScheduler integration matches existing job patterns in backend/jobs/)

---

## Task 9 -- Multi-tenant validation tests (tester)

**Type:** Tests
**Time estimate:** 3-4 hours
**Spec reference:** Section 7 (Concurrency and isolation), Section 5 (DID-to-branch routing)
**Files:** tests/integration/test_multi_clinic_isolation.py (new)

- [ ] **Step 1:** Create test fixture: 10 fake clinics (10 organizations, 10 branches, 10 doctors, 10 DIDs)
- [ ] **Step 2:** Test: 10 simultaneous bookings (one per clinic) -> each gets correct token number, no cross-clinic data leak
- [ ] **Step 3:** Test: branch_id scoping on token queries -> clinic A cannot see clinic B tokens
- [ ] **Step 4:** Test: branch_id scoping on doctor queries -> clinic A cannot see clinic B doctors
- [ ] **Step 5:** Test: audit_log entries have correct branch_id on every row
- [ ] **Step 6:** Test: 1 known-bad case (query WITHOUT branch_id filter) -> returns data from multiple clinics (assert this FAILS isolation, proving the filter is necessary)
- [ ] **Step 7:** Test: Redis key isolation -> token:{doctor_id}:{branch_id_A}:{date} and token:{doctor_id}:{branch_id_B}:{date} are independent

**Acceptance criteria:**
1. tests/integration/test_multi_clinic_isolation.py exists with 7+ test cases
2. All tests GREEN (including the known-bad case that proves isolation is needed)
3. Tests use real Postgres + real Redis (Docker, per tester.md rule 9)
4. No regressions on existing test suite
5. N=10 clinics, not N=2 (prove it at scale, not just pair)

**Dispatch:** tester
**Reviewer:** security-engineer (verify branch_id isolation tests are not trivially passing)

---

## Task 10 -- Production migration to Fly.io self-hosted LiveKit (devops-engineer, Phase 10)

**Type:** Infrastructure
**Time estimate:** 4-6 hours
**Spec reference:** Section 7.1 (LiveKit tiers), Appendix B (LiveKit SIP config)
**Files:** infra/fly.livekit.toml (new), infra/livekit.yaml (new -- LiveKit server config)

- [ ] **Step 1:** Create infra/fly.livekit.toml for Fly.io bom Mumbai deployment (shared-cpu-2x, 1GB RAM)
- [ ] **Step 2:** Create infra/livekit.yaml with SIP bridge enabled, TURN server config, Redis for room state
- [ ] **Step 3:** Deploy LiveKit server to Fly.io bom (fly deploy --config infra/fly.livekit.toml)
- [ ] **Step 4:** Update LIVEKIT_URL env var across all services (agent + backend)
- [ ] **Step 5:** Verify: no trunk re-provisioning needed (same trunk IDs work with new LiveKit URL)
- [ ] **Step 6:** Test: real call routes through self-hosted LiveKit, total RTT <500ms for India patient -> agent response

**Acceptance criteria:**
1. infra/fly.livekit.toml exists with Fly.io bom Mumbai config
2. LiveKit server running on Fly.io (fly status shows healthy)
3. Real inbound call routes through self-hosted LiveKit to agent
4. Total round-trip time (patient speaks -> agent responds) < 500ms
5. No trunk IDs or dispatch rules changed (migration is URL-swap only)

**Dispatch:** devops-engineer
**Reviewer:** voice-agent-engineer (verify agent connects to self-hosted LiveKit without code changes)

---

## Task dependency graph

```
Task 1 (Vobiz confirm) -----> Task 3 (provisioning script)
                          +--> Task 4 (onboarding service)
                          +--> Task 5 (Razorpay webhook)

Task 2 (pool tuning)     -----> independent, can run anytime

Task 3 + Task 4          -----> Task 5 (depends on both)

Task 5                    -----> Task 6 (frontend needs API)

Task 7 (UptimeRobot)     -----> depends on Task 4 (integrates into onboarding)

Task 8 (capacity monitor) ----> independent, can run anytime after Phase 6

Task 9 (isolation tests)  ----> independent, can run now (uses existing schema)

Task 10 (self-hosted LK)  ----> Phase 10, independent of Tasks 1-9
```

**Recommended execution order:**
1. Task 1 (manual, start immediately -- blocking)
2. Task 2 + Task 9 (parallel, no dependencies)
3. Task 3 (after Task 1 answers arrive)
4. Task 4 (after Task 1 answers arrive)
5. Task 5 (after Task 3 + Task 4)
6. Task 6 (after Task 5)
7. Task 7 + Task 8 (parallel, after Task 4)
8. Task 10 (Phase 10, after all else)
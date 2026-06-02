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
